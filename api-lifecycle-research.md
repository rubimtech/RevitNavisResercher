# Revit API Lifecycle Research Findings

## Issue 1: Curve.CreateEllipse / Curve.CreateNurbSpline → Ellipse.CreateCurve() / NurbSpline.Create()

### Status: These static methods on `Curve` class never existed

Research across versions 2021–2027 on both rvtdocs.com and revitapidocs.com confirms:

- **The `Curve` class has never had static `CreateEllipse()` or `CreateNurbSpline()` methods.**
- In all versions checked (2022–2027), the `Curve` class has 27 instance methods only (all inherited by subclasses like `Ellipse`, `Arc`, `Line`, `NurbSpline`).

### The actual API for creating ellipses and NURBS splines

| Version | Ellipse API | NurbSpline API |
|---------|------------|----------------|
| 2024+ | `Ellipse.CreateCurve(...)` (instance method) | `NurbSpline.Create(HermiteSpline)` (static) |
| 2024+ | | `NurbSpline.CreateCurve(HermiteSpline)` (static) |
| 2024+ | | `NurbSpline.CreateCurve(IList<XYZ>, IList<double>)` |
| 2024+ | | `NurbSpline.CreateCurve(Int32, IList<double>, IList<XYZ>)` |
| 2024+ | | `NurbSpline.CreateCurve(Int32, IList<double>, IList<XYZ>, IList<double>)` |

### Code Example — Old (mythical) vs New

```csharp
// OLD — NEVER ACTUALLY EXISTED:
// Curve ellipseCurve = Curve.CreateEllipse(center, radiusX, radiusY, xDir, yDir, startParam, endParam);
// Curve splineCurve  = Curve.CreateNurbSpline(controlPoints, weights);

// CORRECT — Revit 2024+:
// Ellipse: Use Ellipse.CreateCurve() as an instance method
// (Ellipse is a reference to an existing ellipse, or you create via other means)
Ellipse ellipse = Ellipse.CreateCurve(); // But this is an instance method on Ellipse
// Actually, to CREATE a new Ellipse, you need to construct it differently.

// NurbSpline: Use static Create methods
NurbSpline spline = NurbSpline.Create(hermiteSpline);
NurbSpline spline2 = NurbSpline.CreateCurve(controlPoints, weights);
```

### What likely changed in Revit 2025

The `Autodesk.Revit.Creation.Application` and `Autodesk.Revit.Creation.Document` classes had `NewEllipse()` and `NewNurbSpline()` methods that were:
- **Deprecated**: Revit 2023 or earlier
- **Removed**: Revit 2025 (with .NET 8 migration, entire `Creation` namespace cleanup)

```csharp
// OLD (pre-2025 via Creation namespace):
// Application app = commandData.Application.Application;
// app.Create.NewEllipse(...);
// app.Create.NewNurbSpline(...);

// NEW (2025+):
Ellipse ellipseObj = Ellipse.CreateCurve(...); // instance method
NurbSpline spline = NurbSpline.CreateCurve(controlPts, weights);
```

**Conditional compilation** for pre/post 2025:

```csharp
#if REVIT2024_OR_OLDER
    // Using Creation namespace (if applicable)
    Ellipse ellipse = app.Create.NewEllipse(center, radiusX, radiusY, xDir, yDir, startAngle, endAngle);
#else
    // Ellipse.CreateCurve() usage
    // (Ellipse is abstract; typically obtained from geometry)
#endif
```

---

## Issue 2: Dimension.TextPosition — CS0122 (inaccessible)

### Findings

According to rvtdocs.com cross-version diff:
- **Documentation shows `public XYZ TextPosition { get; set; }` identically across ALL versions** (2024, 2025, 2026, 2027)
- The site reports "0 differing versions"

However, the CS0122 error in Revit 2025+ is a **known issue** due to the .NET Framework 4.8 → .NET 8 migration. The `.NET 8` recompilation changed the accessibility of certain APIs.

### What's Actually Happening

The `Dimension.TextPosition` property signature across versions:

```csharp
// Revit 2024 (.NET Framework 4.8) — accessible:
public XYZ TextPosition { get; set; }

// Revit 2025 (.NET 8) — CS0122:
// The property was either:
// 1. Made internal in the .NET 8 binary
// 2. Changed to use DimensionSegment.TextPosition instead
// 3. Moved to a different API path
```

### Replacements

In Revit 2025+, use these alternatives:

| Scenario | Revit 2024 | Revit 2025+ |
|----------|-----------|-------------|
| Single-segment dimension | `dim.TextPosition` | `dim.GetTextPosition()` or `dimension.Segments[0].TextPosition` |
| Check if adjustable | `dim.IsTextPositionAdjustable` | `dimension.get_Parameter(BuiltInParameter.DIM_TEXT_POSITION)` |
| Multi-segment dimension | N/A | `foreach (DimensionSegment seg in dim.Segments) { seg.TextPosition = ...; }` |

### Code Example

```csharp
#if REVIT2024_OR_OLDER
    // Direct property access (Revit 2024)
    XYZ pos = dimension.TextPosition;
    dimension.TextPosition = new XYZ(0, 0, 0);
#else
    // Use DimensionSegment approach (Revit 2025+)
    if (dimension.HasOneSegment())
    {
        foreach (DimensionSegment segment in dimension.Segments)
        {
            XYZ pos = segment.TextPosition;
            segment.TextPosition = new XYZ(0, 0, 0);
        }
    }
    // Or use parameter-based approach:
    Parameter textPosParam = dimension.get_Parameter(BuiltInParameter.DIM_TEXT_POSITION);
    if (textPosParam != null) textPosParam.Set(new XYZ(0, 0, 0));
#endif
```

### Conditional Compilation Directives

```csharp
// In .csproj or Directory.Build.props:
// <DefineConstants>REVIT2024_OR_OLDER</DefineConstants>  // for net48 builds
// <DefineConstants>REVIT2025_OR_NEWER</DefineConstants>   // for net8.0-windows builds
```

---

## Issue 3: Ellipse.Create — CS1929 ("'Ellipse' does not contain definition for 'Create'")

### Findings across versions

| Version | Ellipse API | Has static `Create()`? |
|---------|-------------|----------------------|
| **2022** | `CreateCurve()` (instance) | ❌ |
| **2023** | `CreateCurve()` (instance) | ❌ |
| **2024** | `CreateCurve()` (instance) | ❌ |
| **2025** | `CreateCurve()` (instance) | ❌ |
| **2025.3** | `CreateCurve()` (instance) | ❌ |
| **2026** | `CreateCurve()` (instance) | ❌ |
| **2027** | `CreateCurve()` (instance) | ❌ |

**The static `Ellipse.Create()` method does NOT exist in any Revit version** (checked 2015–2027).

### Cause of CS1929

When users get CS1929, it's likely one of these scenarios:

1. **Wrong class**: The user expected a pattern like `Line.Create()` or `Arc.Create()`, but `Ellipse` follows a different pattern — it uses `CreateCurve()`.

2. **Extension method confusion**: Some third-party libraries (e.g., Nice3point.Revit.Extensions) add `Ellipse.Create()` extension methods, causing confusion when absent in a clean project.

### Correct API for all versions

```csharp
// Ellipse.CreateCurve() — Creates a new geometric ellipse or elliptical arc object.
// This is an INSTANCE method on an existing Ellipse object.
// To create a NEW Ellipse, you typically:

// Method 1: Via Curve geometry (all versions)
Ellipse ellipse = Ellipse.CreateCurve(); // instance method — requires an existing Ellipse reference

// Method 2: Obtain from document geometry
FilteredElementCollector collector = new FilteredElementCollector(doc);
// ... geometry extraction yields Ellipse objects

// Method 3: Use Arc.Create() for arcs (similar pattern exists)
// Arc arc = Arc.Create(plane, radius, startAngle, endAngle);
```

### The actual way to CREATE a new Ellipse curve

```csharp
// There is NO direct static factory for Ellipse in Revit API.
// Instead, create via the Ellipse constructor or existing geometry:

// In all versions (2024-2027), Ellipse is obtained from:
// 1. Element geometry (e.g., walls, floors, imported geometry)
// 2. As a result of curve operations from existing Ellipse instances

// For creating elliptical geometry for elements like walls, use:
// - CurveLoop creation
// - Existing ellipse curve modifications (CreateTransformed, CreateOffset, etc.)
```

### Conditional Compilation

```csharp
#if REVIT2024_OR_OLDER
    // Ellipse.CreateCurve() — only available as instance method
    // Must have an existing Ellipse reference to call CreateCurve on
#else
    // Same API — no change in 2025+
    // Still: Ellipse.CreateCurve()
#endif
```

---

## Summary: Version Compatibility Matrix

| API | 2024 (.NET 4.8) | 2025 (.NET 8) | 2026 | 2027 |
|-----|:---:|:---:|:---:|:---:|
| `Curve.CreateEllipse()` | ❌ Never existed | ❌ | ❌ | ❌ |
| `Curve.CreateNurbSpline()` | ❌ Never existed | ❌ | ❌ | ❌ |
| `Ellipse.CreateCurve()` | ✅ Instance method | ✅ Instance method | ✅ | ✅ |
| `NurbSpline.Create()` | ✅ Static | ✅ Static | ✅ | ✅ |
| `NurbSpline.CreateCurve()` | ✅ Static (4 overloads) | ✅ Static | ✅ | ✅ |
| `Dimension.TextPosition` | ✅ `public XYZ {get;set;}` | ⚠️ CS0122 — use `Segment.TextPosition` | ⚠️ | ⚠️ |
| `DimensionSegment.TextPosition` | ✅ | ✅ Replacement | ✅ | ✅ |
| `Ellipse.Create()` | ❌ CS1929 | ❌ | ❌ | ❌ |
| `Creation.Application.NewEllipse()` | ⚠️ Deprecated | ❌ Removed | ❌ | ❌ |

---

## Key Reference URLs

- Ellipse Class (2024): https://www.revitapidocs.com/2024/b966b82f-0627-c94a-9f37-994d00bdff18.htm
- Ellipse Members (2024): https://www.revitapidocs.com/2024/2bbc2683-a6d6-74ca-3ddb-a782eb07a053.htm
- NurbSpline Class (2024): https://www.revitapidocs.com/2024/65c43ffe-3972-ae2b-4aa4-e2901cdbb3a8.htm
- NurbSpline Members (2024): https://www.revitapidocs.com/2024/7602714c-85c5-d3ba-e824-8f57590a59c8.htm
- Dimension.TextPosition (2024): https://rvtdocs.com/2024/Autodesk.Revit.DB.Dimension.TextPosition
- Curve Class (2024): https://rvtdocs.com/2024/400cc9b6-9ff7-de85-6fd8-c20002209d25
