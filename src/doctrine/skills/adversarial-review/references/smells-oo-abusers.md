# Object-Orientation Abusers — Code Smells

Incomplete or incorrect application of object-oriented principles.

## Switch Statements

**Fix with:** Replace Conditional with Polymorphism, Replace Type Code with Subclasses, Replace Type Code with State/Strategy

**Symptom:** The same switch or if-else chain over a type code appears in several places, and every new variant means hunting down and editing each copy.

**Why it hurts:** Behavior that belongs to the variants is scattered across the codebase instead of living with each variant.

### C#

```csharp
// SMELL
public float NextSample(Instrument inst, float phase)
{
    switch (inst.Type)
    {
        case InstrumentType.Synth: return MathF.Sin(phase * inst.Pitch);
        case InstrumentType.Sampler: return inst.Sample[(int)phase % inst.Sample.Length];
        case InstrumentType.Noise: return _rng.NextSingle() * 2f - 1f;
        default: throw new ArgumentOutOfRangeException();
    }
}
// the same switch reappears in RenderEnvelope() and SaveInstrument()

// REFACTORED
public abstract class Instrument
{
    public abstract float NextSample(float phase);
}
public class Synth : Instrument
{
    public override float NextSample(float phase) => MathF.Sin(phase * Pitch);
}
public class Sampler : Instrument
{
    public override float NextSample(float phase) => Sample[(int)phase % Sample.Length];
}
// MixerService just calls inst.NextSample(phase); a new variant is one new class
```

### Pseudocode

```
SMELL:
function next_sample(inst, phase):
  switch inst.type:
    SYNTH:   return sin(phase * inst.pitch)
    SAMPLER: return inst.sample[phase mod len]
    NOISE:   return random(-1, 1)
// same switch repeated in render_envelope and save

REFACTORED:
class Synth:   next_sample(phase) = sin(phase * pitch)
class Sampler: next_sample(phase) = sample[phase mod len]
class Noise:   next_sample(phase) = random(-1, 1)
caller invokes inst.next_sample(phase)
```

**Verify before flagging:** Only flag if the same type/enum is switched on in 2+ places, or the switch must be edited every time a variant is added; a single switch isolated in a factory or boundary mapping is acceptable.

## Temporary Field

**Fix with:** Extract Class, Introduce Null Object

**Symptom:** Some instance fields are only set and meaningful during one operation; the rest of the time they sit null or stale, and other methods must check for or carefully ignore them.

**Why it hurts:** Readers cannot tell which object state is real, and any method can accidentally observe half-initialized values.

### C#

```csharp
// SMELL
public class SongStore
{
    private byte[] _importBuffer;   // only set during Import()
    private int _importCursor;      // only meaningful during Import()

    public Song Import(string path)
    {
        _importBuffer = File.ReadAllBytes(path);
        _importCursor = 0;
        return new Song(ReadName(), ReadChains()); // both read the fields
    }
}

// REFACTORED
public class SongStore
{
    public Song Import(string path) =>
        new SongReader(File.ReadAllBytes(path)).ReadSong();
}
public class SongReader
{
    private readonly byte[] _buffer;
    private int _cursor;
    public SongReader(byte[] buffer) => _buffer = buffer;
    public Song ReadSong() => new Song(ReadName(), ReadChains());
}
```

### Pseudocode

```
SMELL:
class SongStore:
  import_buffer, import_cursor   // only valid during import()
  import(path):
    import_buffer = read(path); import_cursor = 0
    return Song(read_name(), read_chains())
// every other method must ignore or null-check the fields

REFACTORED:
class SongStore:
  import(path) = SongReader(read(path)).read_song()
class SongReader:
  buffer, cursor                 // always valid for its lifetime
  read_song() = Song(read_name(), read_chains())
```

**Verify before flagging:** Only flag if the field is unset (null/zero) outside a single operation's call chain — check every other method that reads it; a lazily computed cache with a clear invalidation rule is not this smell.

## Refused Bequest

**Fix with:** Replace Inheritance with Delegation, Push Down Method

**Symptom:** A subclass inherits methods or data it does not want, overriding them to throw, no-op, or hide them. The parent's contract is only partially honored.

**Why it hurts:** Callers holding the base type hit runtime surprises, because the subtype silently breaks substitutability.

### C#

```csharp
// SMELL
public class Chain
{
    public virtual void AddPhrase(Phrase p) => _phrases.Add(p);
    public virtual void SetTranspose(int semitones) => _transpose = semitones;
}
public class MetronomeChain : Chain   // fixed click track
{
    public override void AddPhrase(Phrase p) =>
        throw new NotSupportedException("metronome is fixed");
    public override void SetTranspose(int s) =>
        throw new NotSupportedException("metronome cannot transpose");
}

// REFACTORED
public interface IPlayableTrack { IEnumerable<Step> Steps(); }

public class Chain : IPlayableTrack
{
    public void AddPhrase(Phrase p) => _phrases.Add(p);
    public void SetTranspose(int semitones) => _transpose = semitones;
    public IEnumerable<Step> Steps() { /* expand phrases */ }
}
public class MetronomeChain : IPlayableTrack  // no editing API to refuse
{
    public IEnumerable<Step> Steps() => ClickPattern;
}
```

### Pseudocode

```
SMELL:
class MetronomeChain extends Chain:
  add_phrase(p):    throw NotSupported
  set_transpose(s): throw NotSupported
// inherits an editing API it must reject at runtime

REFACTORED:
interface PlayableTrack: steps()
class Chain implements PlayableTrack:
  add_phrase; set_transpose; steps
class MetronomeChain implements PlayableTrack:
  steps = click_pattern
```

**Verify before flagging:** Only flag if the subclass overrides at least one inherited public member to throw, no-op, or hide it, or uses only a small fraction of the parent's interface; merely declining to override virtuals is fine.

## Alternative Classes with Different Interfaces

**Fix with:** Rename Method, Move Method, Extract Superclass

**Symptom:** Two classes do the same conceptual job but expose it under different method names and shapes, so callers must special-case which one they are holding.

**Why it hurts:** The duplication is invisible to search and tooling, so fixes and features land in one class and silently miss the other.

### C#

```csharp
// SMELL
public class SongStore
{
    public Song LoadSong(string name) { /* read .sng file */ }
    public void SaveSong(Song song) { /* write .sng file */ }
}
public class InstrumentBank
{
    public Instrument FetchByName(string name) { /* read .ins file */ }
    public void Persist(Instrument inst) { /* write .ins file */ }
}

// REFACTORED
public interface IAssetStore<T>
{
    T Load(string name);
    void Save(T asset);
}
public class SongStore : IAssetStore<Song>
{
    public Song Load(string name) { /* read .sng file */ }
    public void Save(Song song) { /* write .sng file */ }
}
public class InstrumentBank : IAssetStore<Instrument> { /* Load / Save */ }
```

### Pseudocode

```
SMELL:
class SongStore:      load_song(name); save_song(song)
class InstrumentBank: fetch_by_name(name); persist(inst)
// same load/save job under incompatible names —
// backup code special-cases which store it holds

REFACTORED:
interface AssetStore<T>: load(name); save(asset)
class SongStore implements AssetStore<Song>
class InstrumentBank implements AssetStore<Instrument>
```

**Verify before flagging:** Only flag after confirming the differently named methods do the same job (compare bodies and effects, not just names) and at least one caller branches on which class it holds; similar names over genuinely different behavior pass.
