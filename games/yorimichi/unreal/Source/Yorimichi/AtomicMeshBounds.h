#pragma once
#include "CoreMinimal.h"
class UStaticMesh;

namespace AtomicMeshBounds
{
/** Exact saved MeshDescription LOD0 position-union bounds, including its true vertex sphere.
 * Editor observation only; refuses missing, duplicate, multi-LOD or unavailable source descriptions.
 * Geometry, CPU-access flags and asset build settings are never changed. */
YORIMICHI_API bool MeasureLod0PartsBounds(const TArray<UStaticMesh*>& Parts, FBoxSphereBounds& OutBounds);
/** The same original saved LOD0 union for an explicit one- or three-LOD authored family.
 * Lower LOD geometry never expands the original asset's cached LOD0 bounds. */
YORIMICHI_API bool MeasureAuthoredLod0PartsBounds(const TArray<UStaticMesh*>& Parts, int32 ExpectedLods,
    FBoxSphereBounds& OutBounds);
}
