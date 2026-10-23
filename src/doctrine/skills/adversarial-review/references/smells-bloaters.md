# Bloaters — Code Smells

Code, methods, and classes that have grown so large they are hard to work with.

## Long Method

**Fix with:** Extract Method, Replace Temp with Query, Decompose Conditional

**Symptom:** A method keeps accumulating lines, often with comment headers or blank lines separating its "sections." Reading it requires holding several sub-tasks in your head at once.

**Why it hurts:** Long methods hide duplication, resist testing, and force every reader to re-derive the structure the author failed to name.

### C#

```csharp
// SMELL
public void Save(Song song)
{
    if (string.IsNullOrEmpty(song.Name)) throw new InvalidSongException("name");
    if (song.Chains.Count > MaxChains) throw new InvalidSongException("chains");
    var buffer = new List<byte>();
    buffer.AddRange(Encoding.ASCII.GetBytes(song.Name.PadRight(12)));
    foreach (var chain in song.Chains)
        foreach (var phrase in chain.Phrases)
            buffer.AddRange(phrase.ToBytes());
    File.WriteAllBytes(Path.Combine(_root, song.Name + ".sng"), buffer.ToArray());
}

// REFACTORED
public void Save(Song song)
{
    Validate(song);
    var bytes = Serialize(song);
    WriteToDisk(song.Name, bytes);
}

private void Validate(Song song) { /* name and chain-count rules */ }
private byte[] Serialize(Song song) { /* header + phrase bytes */ }
private void WriteToDisk(string name, byte[] bytes) { /* path + write */ }
```

### Pseudocode

```
SMELL:
function save(song):
  if song.name is empty: fail
  if song.chains.count > MAX: fail
  bytes = encode_header(song.name)
  for chain in song.chains:
    for phrase in chain.phrases:
      bytes += encode(phrase)
  write_file(path_for(song), bytes)

REFACTORED:
function save(song):
  validate(song)
  bytes = serialize(song)
  write_to_disk(song, bytes)
// validate, serialize, write_to_disk each hold one concern
```

**Verify before flagging:** Only flag if the method exceeds ~20 lines or mixes two or more distinct jobs (e.g., validation + serialization + I/O); a short method at a single abstraction level passes even if it looks busy.

## Large Class

**Fix with:** Extract Class, Extract Subclass, Extract Interface

**Symptom:** One class owns many fields and public methods spanning unrelated concerns. Every new feature seems to land in this class "because everything it needs is already there."

**Why it hurts:** Unrelated concerns change for unrelated reasons, so every edit risks breaking behavior it never meant to touch.

### C#

```csharp
// SMELL
public class MixerService
{
    public void SetChannelVolume(int ch, float db) { /* ... */ }
    public void SetChannelPan(int ch, float pan) { /* ... */ }
    public void MuteChannel(int ch) { /* ... */ }
    public void SaveStateToDisk(string path) { /* ... */ }
    public void LoadStateFromDisk(string path) { /* ... */ }
    public void SendMidiClock() { /* ... */ }
    public void HandleMidiCc(int cc, int value) { /* ... */ }
    public string RenderLevelMeters() { /* ... */ }
}

// REFACTORED
public class MixerService                 // mixing rules only
{
    public void SetChannelVolume(int ch, float db) { /* ... */ }
    public void SetChannelPan(int ch, float pan) { /* ... */ }
    public void MuteChannel(int ch) { /* ... */ }
}
public class MixerStateStore { /* Save / Load */ }
public class MidiBridge      { /* clock + CC handling */ }
public class LevelMeterView  { /* meter rendering */ }
```

### Pseudocode

```
SMELL:
class MixerService:
  set_volume(ch, db); set_pan(ch, pan); mute(ch)
  save_state(path); load_state(path)
  send_midi_clock(); handle_midi_cc(cc, val)
  render_level_meters()

REFACTORED:
class MixerService:    set_volume; set_pan; mute
class MixerStateStore: save; load
class MidiBridge:      send_clock; handle_cc
class LevelMeterView:  render
```

**Verify before flagging:** Only flag if you can name two or more unrelated reasons the class would change (e.g., mixing rules vs. file format vs. MIDI protocol), or it has 10+ public members spanning distinct concerns; a large but cohesive class is not this smell.

## Primitive Obsession

**Fix with:** Replace Data Value with Object, Replace Type Code with Class

**Symptom:** Domain concepts (note, velocity, tempo) are passed around as bare ints and strings, with magic sentinel values and clamping rules re-implemented at each call site.

**Why it hurts:** The rules governing the value live nowhere, so every call site must know them and any one of them can get them wrong.

### C#

```csharp
// SMELL
public class Step
{
    public int Note;       // 0-127, but 255 means "note off"
    public int Velocity;   // 0-127, callers must clamp
}
public void Transpose(Step step, int semitones)
{
    if (step.Note == 255) return;   // every caller repeats this sentinel
    step.Note = Math.Clamp(step.Note + semitones, 0, 127);
}

// REFACTORED
public readonly record struct Note(int Value)
{
    public static readonly Note Off = new(-1);
    public Note Transpose(int semitones) =>
        this == Off ? this : new(Math.Clamp(Value + semitones, 0, 127));
}
public class Step { public Note Note; public Velocity Velocity; }

public void Transpose(Step step, int semitones) =>
    step.Note = step.Note.Transpose(semitones);
```

### Pseudocode

```
SMELL:
step.note = 255                  // magic "off" sentinel
if step.note != 255:
  step.note = clamp(step.note + semitones, 0, 127)
// every call site repeats the sentinel and clamp rules

REFACTORED:
Note = value_object(value)
  OFF = special instance
  transpose(n) -> clamped Note; OFF stays OFF
step.note = step.note.transpose(semitones)
```

**Verify before flagging:** Only flag if the primitive carries domain rules (valid range, sentinel value, format) that are enforced or interpreted at 2+ call sites; a plain count or loop index used locally does not qualify.

## Long Parameter List

**Fix with:** Introduce Parameter Object, Preserve Whole Object

**Symptom:** A method takes a growing string of parameters, several of which are fields plucked off the same object at the call site. Call sites are hard to read and easy to get argument order wrong.

**Why it hurts:** Every new option changes the signature and every caller, and transposed same-typed arguments compile fine but behave wrong.

### C#

```csharp
// SMELL
public void RenderPattern(int phraseId, int startStep, int endStep,
    bool showEffects, bool showVelocity, int highlightRow,
    ConsoleColor fg, ConsoleColor bg)
{
    var phrase = _songStore.GetPhrase(phraseId);
    // ... drawing code using all eight values
}
// caller
editor.RenderPattern(phrase.Id, 0, 15, true, false, cursor.Row, t.Fg, t.Bg);

// REFACTORED
public record RenderOptions(
    bool ShowEffects, bool ShowVelocity, int HighlightRow, Theme Theme);

public void RenderPattern(Phrase phrase, StepRange range, RenderOptions options)
{
    // ... drawing code
}
// caller
editor.RenderPattern(phrase, StepRange.All, _viewOptions);
```

### Pseudocode

```
SMELL:
render_pattern(phrase_id, start, end,
               show_fx, show_vel, highlight_row, fg, bg)
// callers pass 8 loose values, mostly copied off
// the phrase, cursor, and theme objects they hold

REFACTORED:
options = { show_fx, show_vel, highlight_row, theme }
render_pattern(phrase, range, options)
```

**Verify before flagging:** Only flag at 4+ parameters where at least two originate from the same source object or are forwarded together to another method; three or fewer parameters, or four genuinely independent values, pass.

## Data Clumps

**Fix with:** Extract Class, Introduce Parameter Object

**Symptom:** The same small group of values (chainId, phraseSlot, stepIndex) travels together through multiple signatures, fields, and locals. Delete one of them and the others stop making sense.

**Why it hurts:** The group is a missing concept, so its invariants and naming are duplicated at every place it appears.

### C#

```csharp
// SMELL
public void SetNote(int chainId, int phraseSlot, int stepIndex, byte note)
{
    _song.Chains[chainId].Phrases[phraseSlot].Steps[stepIndex].Note = note;
}
public void ClearStep(int chainId, int phraseSlot, int stepIndex) { /* ... */ }
public void CopyStep(int srcChain, int srcSlot, int srcStep,
                     int dstChain, int dstSlot, int dstStep) { /* ... */ }
// the same three ints also ride through the undo log and clipboard

// REFACTORED
public readonly record struct StepAddress(int ChainId, int PhraseSlot, int StepIndex);

public void SetNote(StepAddress at, byte note)
{
    _song[at].Note = note;
}
public void ClearStep(StepAddress at) { /* ... */ }
public void CopyStep(StepAddress source, StepAddress destination) { /* ... */ }
```

### Pseudocode

```
SMELL:
set_note(chain_id, phrase_slot, step_index, note)
clear_step(chain_id, phrase_slot, step_index)
copy_step(src_chain, src_slot, src_step,
          dst_chain, dst_slot, dst_step)
// the trio recurs in the undo log and clipboard too

REFACTORED:
StepAddress = { chain_id, phrase_slot, step_index }
set_note(address, note)
clear_step(address)
copy_step(source_address, destination_address)
```

**Verify before flagging:** Only flag if the identical group of 2+ values appears together in 3 or more signatures or field sets; two co-occurrences may be coincidence.
