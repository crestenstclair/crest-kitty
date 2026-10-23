# Dependency Injection

**Classes must not instantiate their own dependencies.**

```csharp
// WRONG
public class Song {
    public RuntimeOverrides Runtime { get; } = new();  // hidden coupling
}

// RIGHT — injectable, with convenience default
public class Song {
    public RuntimeOverrides Runtime { get; }
    public Song() : this(new RuntimeOverrides()) { }
    public Song(RuntimeOverrides runtime) {
        Runtime = runtime;
    }
}
```

**The pattern:** Full constructor accepts all dependencies. Optional parameterless constructor calls it with sensible defaults. Tests use full constructor. Production uses either.

**Apply to:** Any class holding a reference to another class — services, stores, managers, adapters, engines, dependency collections.

**Do NOT apply to:** Value types/structs, local variables inside methods, factory methods whose purpose is object creation.

## Redundant Coupling

Don't expose two paths to the same data.

```csharp
// WRONG — Song accessible via two paths, can diverge
public class ViewManager {
    public Song? Song { get; set; }
    public ISongStore? Store { get; set; }
}

// RIGHT — single path
public class ViewManager {
    public ISongStore? Store { get; set; }
    // access Song via Store.Song
}
```

## Constructor Rules

- Constructors assign dependencies; logic lives in methods.
- No hidden `new` in a class body — inject, with a convenience default constructor for callers who don't care.
- Singleton is global state in disguise; prefer DI. Only use when exactly one instance is a hard requirement.
