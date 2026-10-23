# Couplers — Code Smells

Smells in this family are excessive coupling between classes, or coupling that has been replaced by excessive delegation.

## Feature Envy

**Fix with:** Move Method, Extract Method

**Symptom:** A method spends its time reading and computing over another class's data instead of its own. The logic clearly "wants to live" on the class it interrogates.

**Why it hurts:** The behavior and the data it depends on evolve in separate files, so every change to the data class silently breaks a distant method.

### C#

```csharp
// SMELL
public class PatternEditor
{
    public double GetPhraseSeconds(Phrase phrase)
    {
        double beats = phrase.StepCount / (double)phrase.StepsPerBeat;
        double seconds = beats * 60.0 / phrase.Tempo;
        return seconds * phrase.RepeatCount;
    }
}

// REFACTORED
public class Phrase
{
    public double DurationSeconds()
    {
        double beats = StepCount / (double)StepsPerBeat;
        return beats * 60.0 / Tempo * RepeatCount;
    }
}

public class PatternEditor
{
    public double GetPhraseSeconds(Phrase phrase) => phrase.DurationSeconds();
}
```

### Pseudocode

```
SMELL:
class PatternEditor:
  method phraseSeconds(phrase):
    beats = phrase.stepCount / phrase.stepsPerBeat
    return beats * 60 / phrase.tempo * phrase.repeatCount

REFACTORED:
class Phrase:
  method durationSeconds():
    beats = self.stepCount / self.stepsPerBeat
    return beats * 60 / self.tempo * self.repeatCount
```

**Verify before flagging:** Only flag if the method touches another class's members three or more times while touching its own at most once, and no framework constraint (serializer, controller, mapper) forces it to live where it does.

## Inappropriate Intimacy

**Fix with:** Move Method, Move Field, Change Bidirectional Association to Unidirectional, Hide Delegate

**Symptom:** Two classes reach into each other's fields or hold mutual back-references, each mutating the other's internals directly.

**Why it hurts:** Neither class can change, be tested, or be reused without dragging the other along.

### C#

```csharp
// SMELL
public class Chain
{
    public Song Owner;                    // back-reference into parent
    public List<Phrase> Phrases = new();  // internals exposed raw

    public void Detach() => Owner.Chains.Remove(this);
}

public class Song
{
    public List<Chain> Chains = new();
    public void Add(Chain c) { c.Owner = this; Chains.Add(c); }
}

// REFACTORED
public class Chain
{
    private readonly List<Phrase> _phrases = new();
    public IReadOnlyList<Phrase> Phrases => _phrases;
}

public class Song
{
    private readonly List<Chain> _chains = new();
    public IReadOnlyList<Chain> Chains => _chains;
    public void Add(Chain chain) => _chains.Add(chain);
    public void Remove(Chain chain) => _chains.Remove(chain);
}
```

### Pseudocode

```
SMELL:
class Chain:
  field owner: Song                       // back-reference
  method detach(): owner.chains.remove(self)
class Song:
  method add(c): c.owner = self; chains.append(c)

REFACTORED:
class Chain:
  // no reference back to Song
class Song:
  private chains
  method add(chain): chains.append(chain)
  method remove(chain): chains.remove(chain)
```

**Verify before flagging:** Only flag if the access is mutual — both classes read or mutate the other's non-public state or hold references in both directions; one-way use of a public API is ordinary collaboration, not intimacy.

## Message Chains

**Fix with:** Hide Delegate, Extract Method + Move Method

**Symptom:** A caller navigates a train of objects — `a.GetB().GetC().GetD().Value` — to reach data several hops away. The caller knows the whole intermediate structure.

**Why it hurts:** Every class in the chain becomes a breaking change waiting to happen for every call site that walks it.

### C#

```csharp
// SMELL
public class MixerService
{
    public string GetLeadInstrumentName(SongStore store)
    {
        return store.GetCurrentSong()
                    .GetChain(0)
                    .GetPhrase(0)
                    .GetInstrument()
                    .Name;
    }
}

// REFACTORED
public class Song
{
    public Instrument LeadInstrument() =>
        GetChain(0).GetPhrase(0).GetInstrument();
}

public class MixerService
{
    public string GetLeadInstrumentName(SongStore store) =>
        store.GetCurrentSong().LeadInstrument().Name;
}
```

### Pseudocode

```
SMELL:
name = store.currentSong()
            .chain(0)
            .phrase(0)
            .instrument()
            .name

REFACTORED:
class Song:
  method leadInstrument():
    return chain(0).phrase(0).instrument()
name = store.currentSong().leadInstrument().name
```

**Verify before flagging:** Only flag chains of three or more hops through distinct object types, ideally repeated at multiple call sites; a fluent builder or LINQ chain returning the same object each step is not a message chain.

## Middle Man

**Fix with:** Remove Middle Man, Inline Method

**Symptom:** A class whose public surface is almost entirely one-line pass-throughs to a single delegate, adding no behavior, validation, or translation of its own.

**Why it hurts:** Every new operation must be added twice, and readers must traverse an extra layer that explains nothing.

### C#

```csharp
// SMELL
public class SongStore
{
    private readonly SongRepository _repo = new();

    public Song Load(int id) => _repo.Load(id);
    public void Save(Song song) => _repo.Save(song);
    public void Delete(int id) => _repo.Delete(id);
    public bool Exists(int id) => _repo.Exists(id);
    public List<Song> All() => _repo.All();
}

// REFACTORED
// SongStore removed; callers depend on the repository directly.
public class SongRepository
{
    public Song Load(int id) { /* ... */ }
    public void Save(Song song) { /* ... */ }
    public void Delete(int id) { /* ... */ }
}

// Call site:
Song song = repository.Load(songId);
```

### Pseudocode

```
SMELL:
class SongStore:
  method load(id): return repo.load(id)
  method save(s): repo.save(s)
  method delete(id): repo.delete(id)
  method exists(id): return repo.exists(id)

REFACTORED:
// SongStore deleted; callers use the repository
song = repository.load(songId)
repository.save(song)
```

**Verify before flagging:** Only flag if more than half of the class's public methods are pure one-line delegations to the same object; spare deliberate facades that isolate callers from an unstable or third-party API.
