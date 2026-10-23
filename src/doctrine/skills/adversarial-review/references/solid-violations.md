# SOLID Violations

How each SOLID principle looks when broken, and how to repair it.

## Single Responsibility Violation (SRP)

**Fix with:** Extract Class, Move Method

**Symptom:** One class changes for several unrelated reasons — it holds domain data and also does persistence, rendering, or reporting.

**Why it hurts:** A change to any one concern risks breaking the others, and the class accumulates dependencies from every axis of change.

### C#

```csharp
// VIOLATION
public class Song
{
    public List<Chain> Chains { get; } = new();

    public void SaveToDisk(string path) { /* file I/O */ }
    public Song LoadFromDisk(string path) { /* file I/O */ }
    public byte[] RenderAudio() { /* DSP mixdown */ }
    public string BuildTrackSheet() { /* report formatting */ }
}

// REFACTORED
public class Song
{
    public List<Chain> Chains { get; } = new();
}

public class SongStore { public void Save(Song song, string path) { /* I/O */ } }
public class AudioRenderer { public byte[] Render(Song song) { /* DSP */ } }
public class TrackSheetWriter { public string Build(Song song) { /* report */ } }
```

### Pseudocode

```
VIOLATION:
class Song:
  chains
  method saveToDisk(path)      // persistence concern
  method renderAudio()         // DSP concern
  method buildTrackSheet()     // reporting concern

REFACTORED:
class Song: chains
class SongStore: method save(song, path)
class AudioRenderer: method render(song)
class TrackSheetWriter: method build(song)
```

**Verify before flagging:** Only flag if you can name two or more distinct reasons to change (e.g., storage format vs. audio engine) backed by unrelated dependency clusters in the class — size alone is not a violation.

## Open/Closed Violation (OCP)

**Fix with:** Replace Conditional with Polymorphism, Strategy pattern, handler registration

**Symptom:** Adding a new variant (instrument kind, export format, event type) requires editing an existing switch or if/else ladder rather than adding a new class.

**Why it hurts:** Every extension re-opens and re-risks tested code, and the same conditional tends to metastasize across the codebase.

### C#

```csharp
// VIOLATION
public class MixerService
{
    public float GetDefaultGain(Instrument inst)
    {
        switch (inst.Kind) // edited every time a kind is added
        {
            case InstrumentKind.Sampler: return 0.8f;
            case InstrumentKind.Synth:   return 0.7f;
            case InstrumentKind.Drum:    return 1.0f;
            default: throw new ArgumentException("Unknown kind");
        }
    }
}

// REFACTORED
public abstract class Instrument
{
    public abstract float DefaultGain { get; }
}

public class Sampler : Instrument { public override float DefaultGain => 0.8f; }
public class Synth   : Instrument { public override float DefaultGain => 0.7f; }

public class MixerService
{
    public float GetDefaultGain(Instrument inst) => inst.DefaultGain;
}
```

### Pseudocode

```
VIOLATION:
method gain(instrument):
  switch instrument.kind:
    case SAMPLER: return 0.8
    case SYNTH:   return 0.7
    case DRUM:    return 1.0

REFACTORED:
class Sampler extends Instrument: defaultGain = 0.8
class Synth   extends Instrument: defaultGain = 0.7
method gain(instrument):
  return instrument.defaultGain
```

**Verify before flagging:** Only flag if the same type-conditional appears in two or more places, or the variant list has demonstrably grown in history; a single exhaustive switch in one location can be an acceptable design.

## Liskov Substitution Violation (LSP)

**Fix with:** Replace Inheritance with Delegation, redesign the base contract

**Symptom:** A subtype cannot honor the base type's contract — it throws NotSupportedException, silently no-ops, or tightens preconditions on an inherited operation.

**Why it hurts:** Code written against the base type breaks at runtime depending on which subtype arrives, defeating the point of the abstraction.

### C#

```csharp
// VIOLATION
public class InstrumentBank
{
    public virtual void Add(Instrument inst) { /* stores in a slot */ }
    public virtual Instrument Get(int slot) { /* returns slot */ }
}

public class FactoryPresetBank : InstrumentBank
{
    public override void Add(Instrument inst) =>
        throw new NotSupportedException("Factory banks are read-only.");
}

// REFACTORED
public interface IInstrumentSource
{
    Instrument Get(int slot);
}

public class UserBank : IInstrumentSource
{
    public void Add(Instrument inst) { /* stores in a slot */ }
    public Instrument Get(int slot) { /* returns slot */ }
}

public class FactoryPresetBank : IInstrumentSource
{
    public Instrument Get(int slot) { /* returns preset */ }
}
```

### Pseudocode

```
VIOLATION:
class InstrumentBank:
  method add(inst): store inst
class FactoryPresetBank extends InstrumentBank:
  method add(inst): throw NotSupported   // breaks base contract

REFACTORED:
interface InstrumentSource: method get(slot)
class UserBank implements InstrumentSource:
  method add(inst); method get(slot)
class FactoryPresetBank implements InstrumentSource:
  method get(slot)                       // never promised add()
```

**Verify before flagging:** Only flag if substituting the subtype where the base is expected changes observable behavior — throws, no-ops, or rejects inputs the base accepts; an override that merely extends or specializes behavior is compliant.

## Interface Segregation Violation (ISP)

**Fix with:** Extract Interface (split fat interfaces into role interfaces)

**Symptom:** A wide interface forces implementers to stub or throw for members they do not need, and clients depend on methods they never call.

**Why it hurts:** Every client is recompiled and re-broken by changes to methods it never uses, and stub implementations hide real LSP failures.

### C#

```csharp
// VIOLATION
public interface IModule
{
    void Play();
    void Stop();
    void RenderWaveform();
    void SaveState(string path);
}

public class Metronome : IModule
{
    public void Play() { /* tick */ }
    public void Stop() { /* silence */ }
    public void RenderWaveform() => throw new NotImplementedException();
    public void SaveState(string path) => throw new NotImplementedException();
}

// REFACTORED
public interface IPlayable
{
    void Play();
    void Stop();
}

public interface IWaveformSource { void RenderWaveform(); }
public interface IPersistable { void SaveState(string path); }

public class Metronome : IPlayable
{
    public void Play() { /* tick */ }
    public void Stop() { /* silence */ }
}
```

### Pseudocode

```
VIOLATION:
interface Module:
  play(); stop(); renderWaveform(); saveState(path)
class Metronome implements Module:
  renderWaveform(): throw NotImplemented
  saveState(path):  throw NotImplemented

REFACTORED:
interface Playable: play(); stop()
interface WaveformSource: renderWaveform()
interface Persistable: saveState(path)
class Metronome implements Playable   // only what it needs
```

**Verify before flagging:** Only flag if at least one concrete implementer stubs, throws, or leaves empty a member it was forced to declare; a wide interface that every implementer genuinely fulfills is cohesive, not fat.

## Dependency Inversion Violation (DIP)

**Fix with:** Extract Interface, Dependency Injection

**Symptom:** A high-level policy class constructs its own concrete infrastructure — audio drivers, database stores, framework clients — with `new`, hard-wiring itself to one implementation.

**Why it hurts:** The policy cannot be tested or reused without dragging in real I/O, and swapping the infrastructure means editing the policy.

### C#

```csharp
// VIOLATION
public class MixerService
{
    private readonly WasapiAudioDriver _driver = new WasapiAudioDriver();
    private readonly SqlSongStore _store = new SqlSongStore("Server=prod;...");

    public void PlaySong(int songId)
    {
        Song song = _store.Load(songId);
        _driver.Stream(song.RenderBuffer());
    }
}

// REFACTORED
public interface IAudioDriver { void Stream(byte[] buffer); }
public interface ISongStore { Song Load(int songId); }

public class MixerService
{
    private readonly IAudioDriver _driver;
    private readonly ISongStore _store;

    public MixerService(IAudioDriver driver, ISongStore store) =>
        (_driver, _store) = (driver, store);

    public void PlaySong(int songId) =>
        _driver.Stream(_store.Load(songId).RenderBuffer());
}
```

### Pseudocode

```
VIOLATION:
class MixerService:
  driver = new WasapiAudioDriver()        // concrete framework type
  store  = new SqlSongStore(connString)   // concrete database type
  method playSong(id):
    driver.stream(store.load(id).renderBuffer())

REFACTORED:
class MixerService:
  constructor(driver: AudioDriver, store: SongStore)  // abstractions in
  method playSong(id):
    driver.stream(store.load(id).renderBuffer())
```

**Verify before flagging:** Only flag when a high-level class directly instantiates concrete infrastructure (I/O, database, framework, network) it could not swap in a test; newing up value objects, collections, or other domain types is fine.
