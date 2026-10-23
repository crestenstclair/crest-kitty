# Refactoring Techniques Quick Reference

The `fix:` field of every finding names a technique from this catalog. Reference: [refactoring.guru/refactoring/techniques](https://refactoring.guru/refactoring/techniques).

## Composing Methods

| Technique | When to Apply |
|-----------|---------------|
| **Extract Method** | Long method, code needing comments to explain |
| **Inline Method** | Method body is as clear as its name |
| **Extract Variable** | Complex expression that needs a name |
| **Replace Temp with Query** | Temp used in multiple places, could be method |
| **Split Temporary Variable** | One temp assigned multiple times for different purposes |
| **Replace Method with Method Object** | Long method with local variables preventing extraction |
| **Substitute Algorithm** | Simpler algorithm achieves same result |

## Moving Features Between Objects

| Technique | When to Apply |
|-----------|---------------|
| **Move Method/Field** | Method/field used more by another class |
| **Extract Class** | Class doing work of two |
| **Inline Class** | Class doing almost nothing |
| **Hide Delegate** | Client calls through chain of objects |
| **Remove Middle Man** | Class has too many delegating methods |

## Organizing Data

| Technique | When to Apply |
|-----------|---------------|
| **Replace Magic Number with Constant** | Literal numbers scattered through code |
| **Replace Data Value with Object** | Primitive carrying domain meaning and rules |
| **Encapsulate Field** | Public field should be accessed via methods |
| **Encapsulate Collection** | Getter returns raw collection |
| **Change Bidirectional Association to Unidirectional** | One side of a two-way link doesn't actually need it |
| **Replace Type Code with Class** | Type code needs validation or meaning but doesn't branch behavior |
| **Replace Type Code with Subclasses** | Type code affects behavior |
| **Replace Type Code with State/Strategy** | Type code changes at runtime |

## Simplifying Conditionals

| Technique | When to Apply |
|-----------|---------------|
| **Decompose Conditional** | Complex condition with large if/else blocks |
| **Consolidate Conditional Expression** | Multiple conditions yield same result |
| **Replace Nested Conditional with Guard Clauses** | Deep nesting obscures normal path |
| **Replace Conditional with Polymorphism** | Switch/if-else on type |
| **Introduce Null Object** | Repeated null checks for same object |

## Simplifying Method Calls

| Technique | When to Apply |
|-----------|---------------|
| **Rename Method** | Name doesn't reveal intent |
| **Separate Query from Modifier** | Method both returns value and changes state |
| **Parameterize Method** | Multiple methods do similar things |
| **Introduce Parameter Object** | Several params always travel together |
| **Preserve Whole Object** | Passing several fields of the same object |
| **Remove Parameter** | Parameter no longer used by the method body |
| **Replace Constructor with Factory Method** | Constructor logic is complex or needs polymorphism |

## Dealing with Generalization

| Technique | When to Apply |
|-----------|---------------|
| **Pull Up Method/Field** | Duplicated across subclasses |
| **Push Down Method/Field** | Used by only one subclass |
| **Extract Subclass/Superclass/Interface** | Subset of features or common behavior |
| **Collapse Hierarchy** | Subclass barely differs from parent |
| **Replace Inheritance with Delegation** | Subclass uses only a fraction of superclass |

## When to Refactor

Reference: [refactoring.guru/refactoring/when](https://refactoring.guru/refactoring/when)

- **Rule of Three:** First time, just do it. Second time, wince but repeat. Third time, refactor.
- **When adding a feature:** Clean up surrounding code first — easier to add to clean code.
- **When fixing a bug:** Bugs hide in messy code. Clean it and errors surface.
- **During code review:** Last chance to tidy before merge.
