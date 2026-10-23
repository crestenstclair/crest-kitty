# Dispensables — Code Smells

Pointless code whose absence would make the codebase cleaner.

## Duplicate Code

**Fix with:** Extract Method, Pull Up Method, Substitute Algorithm

**Symptom:** The same logic — here, note transposition with pitch clamping — appears in more than one place, copied rather than shared.

**Why it hurts:** A fix or rule change applied to one copy silently misses the others.

### C#

```csharp
// SMELL
public class Phrase
{
    public void Transpose(int semis) =>
        Notes.ForEach(n => n.Pitch = Math.Clamp(n.Pitch + semis, 0, 127));
}
public class Chain
{
    public void Transpose(int semis)
    {
        foreach (var p in Phrases)
            foreach (var n in p.Notes)
                n.Pitch = Math.Clamp(n.Pitch + semis, 0, 127);
    }
}

// REFACTORED
public class Phrase
{
    public void Transpose(int semis) =>
        Notes.ForEach(n => n.Pitch = Math.Clamp(n.Pitch + semis, 0, 127));
}
public class Chain
{
    public void Transpose(int semis) =>
        Phrases.ForEach(p => p.Transpose(semis));
}
```

### Pseudocode

```
SMELL:
Phrase.transpose(n): for note in notes: note.pitch = clamp(note.pitch + n)
Chain.transpose(n):  for phrase in phrases:
                         for note in phrase.notes:
                             note.pitch = clamp(note.pitch + n)

REFACTORED:
Phrase.transpose(n): for note in notes: note.pitch = clamp(note.pitch + n)
Chain.transpose(n):  for phrase in phrases: phrase.transpose(n)
```

**Verify before flagging:** Only flag fragments of three or more lines (or one nontrivial expression) that must change together; coincidental similarity that can evolve independently is not duplication.

## Lazy Class

**Fix with:** Inline Class, Collapse Hierarchy

**Symptom:** A class holds no state or logic of its own and merely forwards every call to another class.

**Why it hurts:** It adds a layer of indirection that readers must traverse for zero benefit.

### C#

```csharp
// SMELL
public class ChainNavigator
{
    private readonly Chain _chain;
    public ChainNavigator(Chain chain) => _chain = chain;
    public Phrase Current() => _chain.CurrentPhrase;
    public void Next() => _chain.Advance();
    public bool AtEnd() => _chain.IsFinished;
}
var nav = new ChainNavigator(chain);
while (!nav.AtEnd()) { Play(nav.Current()); nav.Next(); }

// REFACTORED
// ChainNavigator deleted; callers use Chain directly
while (!chain.IsFinished)
{
    Play(chain.CurrentPhrase);
    chain.Advance();
}
// Chain already exposes the whole navigation surface:
// CurrentPhrase, Advance(), IsFinished
```

### Pseudocode

```
SMELL:
class ChainNavigator(chain):
    current() -> chain.current_phrase
    next()    -> chain.advance()
    at_end()  -> chain.is_finished
# no state, no logic — pure forwarding

REFACTORED:
delete ChainNavigator
callers use chain.current_phrase / chain.advance() / chain.is_finished
```

**Verify before flagging:** Only flag if the class holds no state of its own and every public member is a one-line delegation; an interface seam required by tests or DI is exempt.

## Data Class

**Fix with:** Move Method, Encapsulate Field, Encapsulate Collection

**Symptom:** A class exposes only public fields or trivial getters/setters, while the behavior that operates on that data lives in other classes.

**Why it hurts:** The data's invariants are unguarded, so any class anywhere can corrupt them.

### C#

```csharp
// SMELL
public class Song
{
    public List<Chain> Chains = new();
    public int Tempo;
}
public class PatternEditor
{
    public int TotalSteps(Song s)
    {
        var steps = 0;
        foreach (var c in s.Chains) steps += c.Phrases.Count * 16;
        return steps;
    }
}

// REFACTORED
public class Song
{
    private readonly List<Chain> _chains = new();
    public IReadOnlyList<Chain> Chains => _chains;
    public int Tempo { get; set; }
    public void AddChain(Chain c) => _chains.Add(c);
    public int TotalSteps() =>
        _chains.Sum(c => c.Phrases.Count * 16);
}
// PatternEditor now calls song.TotalSteps()
```

### Pseudocode

```
SMELL:
class Song: chains = [], tempo = 0   # fields only, no behavior
class PatternEditor:
    total_steps(song): sum over song.chains of phrase_count * 16

REFACTORED:
class Song:
    private chains; read-only view + add_chain(c)
    total_steps(): sum over chains of phrase_count * 16
```

**Verify before flagging:** Only flag when at least one other class both reads and writes the fields to implement behavior; pure DTOs at serialization or API boundaries are exempt.

## Dead Code

**Fix with:** Delete it (safe removal via version control)

**Symptom:** Methods with no callers, commented-out blocks, or branches that can never execute linger in the codebase "just in case."

**Why it hurts:** Readers and tools keep paying to understand and maintain code that never runs.

### C#

```csharp
// SMELL
public class MixerService
{
    public void ApplyGain(int ch, float db) => _channels[ch].Gain = db;
    // pre-2.0 gain path, kept "just in case" — no callers
    private void ApplyGainLegacy(int ch, float db)
    {
        // var curve = LoadCurve("legacy.tbl");
        // _channels[ch].Gain = curve.Map(db);
    }
    public void Mute(int ch)
    {
        if (false) LogVerbose("mute"); // never runs
        _channels[ch].Muted = true;
    }
}

// REFACTORED
public class MixerService
{
    public void ApplyGain(int ch, float db) => _channels[ch].Gain = db;
    public void Mute(int ch) => _channels[ch].Muted = true;
}
// Legacy path and dead branch deleted outright;
// git log -S "ApplyGainLegacy" recovers them if ever needed.
```

### Pseudocode

```
SMELL:
apply_gain(ch, db): channels[ch].gain = db
apply_gain_legacy(ch, db): <commented-out body>   # no callers
mute(ch):
    if false: log("mute")                          # unreachable
    channels[ch].muted = true

REFACTORED:
apply_gain(ch, db): channels[ch].gain = db
mute(ch): channels[ch].muted = true
# removed code lives on in version control
```

**Verify before flagging:** Only flag after find-usages shows zero references AND you have checked for reflection, DI registration, serialization, and external/public API callers.

## Speculative Generality

**Fix with:** Collapse Hierarchy, Inline Class, Remove Parameter

**Symptom:** Abstract base classes with one subclass, hooks nobody overrides, and parameters nobody passes — built for a future that never arrived.

**Why it hurts:** Every reader pays the comprehension cost of flexibility no caller uses.

### C#

```csharp
// SMELL
public abstract class InstrumentBankBase
{
    public abstract Instrument Load(int slot, string variant);
    protected virtual void OnPreload(object context) { } // never overridden
}
public class InstrumentBank : InstrumentBankBase   // the only subclass
{
    public override Instrument Load(int slot, string variant)
        => _slots[slot];                           // variant never used
}

// REFACTORED
public class InstrumentBank
{
    private readonly Instrument[] _slots = new Instrument[128];

    public Instrument Load(int slot) => _slots[slot];
}
// Base class collapsed; unused hook and parameter removed.
// Reintroduce the abstraction when a second bank type actually exists.
```

### Pseudocode

```
SMELL:
abstract InstrumentBankBase:
    load(slot, variant)      # variant unused everywhere
    on_preload(context): {}  # hook never overridden
InstrumentBank extends InstrumentBankBase   # only subclass

REFACTORED:
class InstrumentBank:
    load(slot): return slots[slot]
```

**Verify before flagging:** Only flag when the abstraction has exactly one implementation and no test or caller uses the extension point; published library surface area is exempt.

## Excessive Comments

**Fix with:** Extract Method, Rename Method (make code self-explanatory)

**Symptom:** A method needs a running commentary of "what this block does" comments to be readable, often paired with a vague method name.

**Why it hurts:** Comments drift out of sync with the code they describe, while the underlying structure stays opaque.

### C#

```csharp
// SMELL
public void Proc(Song s)
{
    // remove phrases that contain no notes
    foreach (var c in s.Chains)
        c.Phrases.RemoveAll(p => p.Notes.Count == 0);
    // renumber the remaining chains sequentially
    for (var i = 0; i < s.Chains.Count; i++)
        s.Chains[i].Index = i;
    // recompute song length for the transport display
    _transport.Steps = s.Chains.Sum(c => c.Phrases.Count * 16);
}

// REFACTORED
public void CompactSong(Song s)
{
    RemoveEmptyPhrases(s);
    RenumberChains(s);
    RefreshTransportLength(s);
}
private void RemoveEmptyPhrases(Song s) =>
    s.Chains.ForEach(c => c.Phrases.RemoveAll(p => p.Notes.Count == 0));
// RenumberChains and RefreshTransportLength extracted the same way
```

### Pseudocode

```
SMELL:
proc(song):
    # remove phrases with no notes
    <loop over chains deleting empty phrases>
    # renumber remaining chains
    <loop assigning sequential indexes>

REFACTORED:
compact_song(song):
    remove_empty_phrases(song)
    renumber_chains(song)
    refresh_transport_length(song)
```

**Verify before flagging:** Only flag comments that restate what the code does, and only when a method needs three or more of them to be readable; "why" comments (workarounds, invariants, spec links) are keepers.
