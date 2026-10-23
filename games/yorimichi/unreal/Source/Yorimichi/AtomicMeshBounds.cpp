#include "AtomicMeshBounds.h"
#include "Engine/StaticMesh.h"
#if WITH_EDITOR
#include "MeshDescription.h"
#include "StaticMeshAttributes.h"
#endif

/** @cc [owner:fontanierh,label:correctness] authored-lod0-original-bounds
 * The explicit one- or three-LOD family MUST preserve the original saved LOD0
 * MeshDescription bounds with non-orphan vertex/double arithmetic. Lower LODs,
 * render buffers and an AABB-diagonal sphere MUST NOT replace or expand them.
 * Missing, duplicate, nonfinite or unexpected-LOD source data MUST refuse. */
bool AtomicMeshBounds::MeasureAuthoredLod0PartsBounds(const TArray<UStaticMesh*>& Parts, int32 ExpectedLods,
    FBoxSphereBounds& OutBounds)
{
    OutBounds = FBoxSphereBounds(ForceInit);
#if WITH_EDITOR
    if (Parts.IsEmpty() || (ExpectedLods != 1 && ExpectedLods != 3)) return false;
    TSet<const UStaticMesh*> Seen;
    FBox Box(ForceInit);
    for (UStaticMesh* Mesh : Parts)
    {
        if (!Mesh || Seen.Contains(Mesh) || Mesh->GetNumLODs() != ExpectedLods) return false;
        Seen.Add(Mesh);
        const FMeshDescription* Description = Mesh->GetMeshDescription(0);
        if (!Description || Description->Triangles().Num() < 1) return false;
        const auto Positions = FStaticMeshConstAttributes(*Description).GetVertexPositions();
        for (const FVertexID Vertex : Description->Vertices().GetElementIDs())
        {
            if (Description->IsVertexOrphaned(Vertex)) continue;
            const FVector Position(Positions[Vertex]);
            if (Position.ContainsNaN()) return false;
            Box += Position;
        }
    }
    if (!Box.IsValid) return false;
    Box.GetCenterAndExtents(OutBounds.Origin, OutBounds.BoxExtent);
    OutBounds.SphereRadius = 0.;
    for (UStaticMesh* Mesh : Parts)
    {
        const FMeshDescription* Description = Mesh->GetMeshDescription(0);
        const auto Positions = FStaticMeshConstAttributes(*Description).GetVertexPositions();
        for (const FVertexID Vertex : Description->Vertices().GetElementIDs())
            if (!Description->IsVertexOrphaned(Vertex))
                OutBounds.SphereRadius = FMath::Max<FVector::FReal>(
                    (FVector(Positions[Vertex]) - OutBounds.Origin).Size(), OutBounds.SphereRadius);
    }
    return !OutBounds.ContainsNaN() && OutBounds.SphereRadius > 0.;
#else
    return false;
#endif
}

/** @cc [owner:fontanierh,label:correctness] atomic-lod0-original-bounds
 * Independent rigid parts MUST preserve the imported predecessor's saved LOD0
 * MeshDescription bounds, using the engine's non-orphan vertex/double arithmetic.
 * Missing, duplicate, nonfinite, multi-LOD or inaccessible source data MUST refuse.
 * Render-buffer float32 bounds and an AABB-diagonal sphere MUST NOT substitute for
 * the original saved asset's box and true vertex sphere. */
bool AtomicMeshBounds::MeasureLod0PartsBounds(const TArray<UStaticMesh*>& Parts, FBoxSphereBounds& OutBounds)
{
    return MeasureAuthoredLod0PartsBounds(Parts, 1, OutBounds);
}
