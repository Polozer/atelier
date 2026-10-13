#include "MeshImportAudit.h"
#include "Engine/StaticMesh.h"
#include "Engine/SkeletalMesh.h"
#include "Animation/MorphTarget.h"
#include "Rendering/SkeletalMeshRenderData.h"
#include "StaticMeshResources.h"
#include "Misc/FileHelper.h"

bool UMeshImportAudit::DumpMeshTriangles(UStaticMesh* Mesh, FVector Origin, const FString& Path)
{
    if (!Mesh || !Mesh->GetRenderData() || Mesh->GetRenderData()->LODResources.IsEmpty()) return false;
    const FStaticMeshLODResources& LOD = Mesh->GetRenderData()->LODResources[0];
    const FIndexArrayView Indices = LOD.IndexBuffer.GetArrayView();
    const FPositionVertexBuffer& Positions = LOD.VertexBuffers.PositionVertexBuffer;
    TArray<uint8> Bytes;
    Bytes.Reserve(Indices.Num() * 3 * sizeof(double));
    for (int32 Index = 0; Index < Indices.Num(); ++Index)
    {
        const FVector P = Origin + FVector(Positions.VertexPosition(Indices[Index]));
        for (double Value : {P.X, P.Y, P.Z})
            Bytes.Append(reinterpret_cast<const uint8*>(&Value), sizeof(double));
    }
    return FFileHelper::SaveArrayToFile(Bytes, *Path);
}

bool UMeshImportAudit::DumpSkeletalMesh(USkeletalMesh* Mesh, const FString& Path)
{
    FSkeletalMeshRenderData* Render = Mesh ? Mesh->GetResourceForRendering() : nullptr;
    if (!Render || Render->LODRenderData.IsEmpty()) return false;
    const FSkeletalMeshLODRenderData& LOD = Render->LODRenderData[0];
    const FReferenceSkeleton& Skeleton = Mesh->GetRefSkeleton();
    const FPositionVertexBuffer& Positions = LOD.StaticVertexBuffers.PositionVertexBuffer;
    const FStaticMeshVertexBuffer& Vertices = LOD.StaticVertexBuffers.StaticMeshVertexBuffer;
    const FSkinWeightVertexBuffer* Weights = LOD.GetSkinWeightVertexBuffer();
    if (!Weights) return false;
    TArray<FString> Lines;
    for (const FSkelMeshRenderSection& Section : LOD.RenderSections)
        for (uint32 V = Section.BaseVertexIndex; V < Section.BaseVertexIndex + Section.NumVertices; ++V)
        {
            const FVector3f P = Positions.VertexPosition(V);
            const FVector4f N = Vertices.VertexTangentZ(V);
            const FVector2f UV = Vertices.GetVertexUV(V, 0);
            FString Line = FString::Printf(TEXT("v %d %.6f %.6f %.6f %.5f %.5f %.5f %.6f %.6f"), Section.MaterialIndex,
                                           P.X, P.Y, P.Z, N.X, N.Y, N.Z, UV.X, UV.Y);
            const FSkinWeightInfo Info = Weights->GetVertexSkinWeights(V);
            for (int32 I = 0; I < MAX_TOTAL_INFLUENCES; ++I)
                if (Info.InfluenceWeights[I] > 0)
                    Line += FString::Printf(TEXT(" %s:%.5f"), *Skeleton.GetBoneName(Section.BoneMap[Info.InfluenceBones[I]]).ToString(),
                                            Info.InfluenceWeights[I] / 65535.f);
            Lines.Add(Line);
        }
    TArray<uint32> Indices;
    LOD.MultiSizeIndexContainer.GetIndexBuffer(Indices);
    for (int32 I = 0; I + 2 < Indices.Num(); I += 3)
        Lines.Add(FString::Printf(TEXT("f %u %u %u"), Indices[I], Indices[I + 1], Indices[I + 2]));
    for (const UMorphTarget* Morph : Mesh->GetMorphTargets())
    {
        if (!Morph) continue;
        int32 Num = 0;
        const FMorphTargetDelta* Deltas = Morph->GetMorphTargetDelta(0, Num);
        for (int32 I = 0; I < Num; ++I)
            Lines.Add(FString::Printf(TEXT("m %s %u %.6f %.6f %.6f"), *Morph->GetName(), Deltas[I].SourceIdx,
                                      Deltas[I].PositionDelta.X, Deltas[I].PositionDelta.Y, Deltas[I].PositionDelta.Z));
    }
    return FFileHelper::SaveStringArrayToFile(Lines, *Path);
}
