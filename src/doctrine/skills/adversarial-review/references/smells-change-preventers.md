# Change Preventers — Code Smells

Structures that force one change to be made in many places.

## Divergent Change

**Fix with:** Extract Class

**Symptom:** One class is edited for several unrelated reasons — a file-format change, a MIDI-mapping change, and an audio-engine change all land in the same class.

**Why it hurts:** Every axis of change risks breaking the others, so the class never stabilizes.

### C#

```csharp
// SMELL
public class SongStore
{
    private readonly string _root;
    public void Save(Song song) { /* .sng format rules */ }
    public Song Load(string path) { /* .sng format rules */ }
    public byte[] ExportMidi(Song song) { /* MIDI mapping rules */ }
    public byte[] RenderWav(Song song) { /* audio engine settings */ }
}

// REFACTORED
public class SongStore
{
    public void Save(Song song) { /* .sng format rules */ }
    public Song Load(string path) { /* .sng format rules */ }
}
public class SongExporter
{
    public byte[] ExportMidi(Song song) { /* MIDI mapping rules */ }
    public byte[] RenderWav(Song song) { /* audio engine settings */ }
}
```

### Pseudocode

```
SMELL:
class SongStore:
    save(song)         # edited when file format changes
    load(path)         # edited when file format changes
    export_midi(song)  # edited when MIDI mapping changes
    render_wav(song)   # edited when audio engine changes

REFACTORED:
class SongStore:    save(song), load(path)
class SongExporter: export_midi(song), render_wav(song)
# each future change now lands in exactly one class
```

**Verify before flagging:** Only flag if you can name two concrete, unrelated changes (or find two in git history) that would each modify a disjoint subset of the class's members.

## Shotgun Surgery

**Fix with:** Move Method, Move Field, Inline Class

**Symptom:** One conceptual change — e.g. widening the valid tempo range — requires small coordinated edits scattered across many classes.

**Why it hurts:** It is easy to miss one of the scattered edit sites and ship an inconsistent rule.

### C#

```csharp
// SMELL
public class PatternEditor
{
    public void SetTempo(Song s, int bpm) => s.Tempo = Math.Clamp(bpm, 40, 300);
}
public class SongStore
{
    private int ReadTempo(int raw) => raw < 40 ? 120 : Math.Min(raw, 300);
}
public class MixerService
{
    public void Sync(Song s) { if (s.Tempo < 40) s.Tempo = 120; }
}

// REFACTORED
public class Song
{
    public const int MinTempo = 40, MaxTempo = 300;
    private int _tempo = 120;
    public int Tempo
    {
        get => _tempo;
        set => _tempo = Math.Clamp(value, MinTempo, MaxTempo);
    }
}
// PatternEditor, SongStore, MixerService now just assign song.Tempo
```

### Pseudocode

```
SMELL:
PatternEditor.set_tempo: song.tempo = clamp(bpm, 40, 300)
SongStore.load:          song.tempo = clamp(raw, 40, 300)
MixerService.sync:       if song.tempo < 40: song.tempo = 120
# widening the tempo range means editing three classes

REFACTORED:
Song.tempo setter: clamp(value, MIN_TEMPO, MAX_TEMPO)
other classes:     song.tempo = value
# widening the tempo range edits one class
```

**Verify before flagging:** Only flag if a single named change would force edits in three or more classes; two call sites sharing one rule is normal reuse, not shotgun surgery.

## Parallel Inheritance Hierarchies

**Fix with:** Move Method, Move Field (collapse one hierarchy into the other)

**Symptom:** Adding a subclass to one hierarchy always forces a matching subclass in another, and the class-name prefixes mirror each other (SynthInstrument / SynthVoiceRenderer).

**Why it hurts:** Every new variant costs two coordinated classes instead of one.

### C#

```csharp
// SMELL
public abstract class Instrument { public string Name = ""; }
public class SynthInstrument : Instrument { }
public class SamplerInstrument : Instrument { }
public abstract class VoiceRenderer { public abstract float Render(Note n); }
public class SynthVoiceRenderer : VoiceRenderer
{ public override float Render(Note n) => Oscillate(n); }
public class SamplerVoiceRenderer : VoiceRenderer
{ public override float Render(Note n) => PlaySample(n); }

// REFACTORED
public abstract class Instrument
{
    public string Name = "";
    public abstract float RenderVoice(Note n);
}
public class SynthInstrument : Instrument
{ public override float RenderVoice(Note n) => Oscillate(n); }
public class SamplerInstrument : Instrument
{ public override float RenderVoice(Note n) => PlaySample(n); }
```

### Pseudocode

```
SMELL:
Instrument <- SynthInstrument, SamplerInstrument
Renderer   <- SynthRenderer,   SamplerRenderer
# adding FmInstrument forces adding FmRenderer too

REFACTORED:
Instrument <- SynthInstrument, SamplerInstrument
each subclass implements render_voice(note)
# adding FmInstrument is one new class
```

**Verify before flagging:** Only flag when the two hierarchies contain two or more name-prefix-matched subclass pairs AND adding a variant demonstrably requires a new class in both.
