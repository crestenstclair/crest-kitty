# SOLID Principles

## Single Responsibility (SRP)

Each class has **one reason to change** — one actor it serves.

```csharp
// WRONG — one class handles every domain
public void Dispatch(Action action) {
    switch (action) {
        case PhraseEdit: ...
        case ChainEdit: ...
        case MixerEdit: ...
    }
}

// RIGHT — handler per domain
public interface IActionHandler {
    bool CanHandle(SongAction action);
    void Handle(Song song, SongAction action);
}
// PhraseActionHandler, ChainActionHandler, etc.
```

**Test:** Can you describe what the class does without using "and"?

## Open/Closed (OCP)

Open for extension, closed for modification. Adding a new type should mean adding a new class, not editing a switch statement.

```csharp
// WRONG — every new export format edits this method
public void Export(Song song, string format) {
    if (format == "midi") { ... }
    else if (format == "wav") { ... }
}

// RIGHT — new format = new class, registered once
public interface ISongExporter {
    string Format { get; }
    void Export(Song song, Stream output);
}
```

**Techniques:** Strategy pattern, handler registration, plugin architectures.

## Liskov Substitution (LSP)

Any implementation of an interface must be usable wherever the interface is expected. Subtypes must honor the base contract — no surprising exceptions, no narrowed preconditions.

```csharp
// WRONG — subtype breaks the base contract
public class ReadOnlySongStore : SongStore {
    public override void Save(Song song)
        => throw new NotSupportedException();  // callers of SongStore now crash
}

// RIGHT — the contract itself is split so no implementor must lie
public interface ISongReader { Song GetSong(); }
public interface ISongWriter { void SaveSong(Song song); }
```

**Test:** Can you swap any implementation without the caller knowing?

## Interface Segregation (ISP)

No client should depend on methods it doesn't use. Split fat interfaces into focused ones.

```csharp
// WRONG — view forced to depend on write methods it never calls
public interface ISongManager {
    Song GetSong();
    void SaveSong(Song song);
    void ExportMidi(Song song);
    void ImportMidi(string path);
}

// RIGHT — read-only consumers get a focused interface
public interface ISongReader { Song GetSong(); }
public interface ISongWriter { void SaveSong(Song song); }
```

## Dependency Inversion (DIP)

High-level modules depend on abstractions, not concretions.

```csharp
// WRONG — depends on concrete Godot Node
public class ViewManager {
    public InputRouter Router { get; set; }
}

// RIGHT — depends on testable abstraction
public class ViewManager {
    public IInputRouter Router { get; set; }
}
```

**When to create an interface:**

- Any class another class depends on
- Especially classes that touch framework, I/O, audio, or network
- NOT for data-only classes (records, structs, enums)
