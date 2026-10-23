# Clean Code Rules

## Naming

| Rule | Example |
|------|---------|
| Reveal intent | `elapsedTimeInMs` not `t` |
| Pronounceable | `customerAddress` not `cstmrAddr` |
| Searchable | Named constants not magic numbers |
| One word per concept | Don't mix `fetch`/`get`/`retrieve` for the same operation |
| Noun for classes | `SongStore`, `PhraseEditor` |
| Verb for methods | `CalculateTotal()`, `ParseInput()` |

## Functions

- **Small.** If it needs a comment explaining what a block does, extract that block.
- **Do one thing.** One level of abstraction per function.
- **Few arguments.** 0-2 ideal, 3 maximum. Beyond that, introduce a parameter object.
- **No side effects.** A function named `CheckPassword` shouldn't also initialize a session.
- **Command/Query separation.** Functions either do something OR answer something, not both.

## Comments

**Comment only what the code cannot say.**

| Keep | Remove |
|------|--------|
| Legal/license headers | Restating what code does: `// increment i` |
| Explanation of intent or non-obvious "why" | Commented-out code blocks |
| Warning of consequences | Journal/changelog comments |
| TODO with ticket reference | Redundant Javadoc on obvious methods |

## Error Handling

- Prefer exceptions over error codes
- Don't return null — use Null Object pattern or throw
- Don't pass null — validate at system boundaries
- Write try-catch at the right level of abstraction

## Boundaries

- Wrap third-party APIs behind your own interfaces
- Keep framework-specific code at the edges, pure logic at the center
- Learning tests: write tests against third-party APIs to verify your understanding

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Creating interface for every class | Only interface classes that other classes depend on. Data objects don't need interfaces. |
| Premature abstraction | Wait for the Rule of Three. Three similar lines > one premature abstraction. |
| God class | Split by responsibility. Each class serves one actor. |
| Constructor doing work | Constructors assign dependencies. Put logic in methods. |
| Hidden `new` in class body | Inject via constructor. Use convenience default constructor for callers who don't care. |
| Singleton overuse | Singleton is global state. Prefer DI. Only use when exactly one instance is a hard requirement. |
| Deep inheritance hierarchies | Prefer composition. Flatten to 2 levels max. |
| Mixing command and query | Method either changes state OR returns a value, never both. |
