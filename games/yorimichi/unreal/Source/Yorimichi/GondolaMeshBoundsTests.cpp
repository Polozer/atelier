#include "AtomicMeshBounds.h"
#include "GondolaService.h"
#if WITH_DEV_AUTOMATION_TESTS && WITH_EDITOR
#include "Misc/AutomationTest.h"
#include "Engine/StaticMesh.h"
#include "StaticMeshResources.h"
#include "MeshDescription.h"
#include "StaticMeshAttributes.h"
#include "UObject/StrongObjectPtr.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGondolaSourceBoundsTest,"Yorimichi.Gondola.AtomicLogicalBounds",
    EAutomationTestFlags_ApplicationContextMask|EAutomationTestFlags::EngineFilter)
bool FGondolaSourceBoundsTest::RunTest(const FString&)
{
    TArray<TStrongObjectPtr<UStaticMesh>> Owners;
    TArray<UStaticMesh*> Parts;
    FMeshDescription Whole;FStaticMeshAttributes WholeAttributes(Whole);WholeAttributes.Register();
    const TArray<TArray<FVector3f>> Positions{
        {{.1f,.2f,.3f},{1.3f,.7f,.5f},{.4f,1.9f,.8f}},
        {{2.7f,.4f,.9f},{4.1f,.6f,1.2f},{3.3f,2.3f,.2f}}};
    for (int32 Index=0;Index<2;++Index)
    {
        UObject* Outer=NewObject<UGondolaLogicalBoundsData>();
        const FName Name(*FString::Printf(TEXT("GD_L1_Rope_LOD0_Piece%02d"),Index));
        Owners.Emplace(NewObject<UStaticMesh>(Outer,Name));
        UStaticMesh* Mesh=Owners.Last().Get();auto Data=MakeUnique<FStaticMeshRenderData>();
        for (int32 Lod=0;Lod<3;++Lod)
        {
            auto* Resources=new FStaticMeshLODResources();Data->LODResources.Add(Resources);
            // Deliberately larger lower levels must not expand cached LOD0 bounds.
            auto Vertices=Positions[Index];
            if (Lod>0) for (auto& Vertex:Vertices) Vertex+=FVector3f(1000.f*Lod,0.f,0.f);
            Resources->VertexBuffers.PositionVertexBuffer.Init(Vertices,true);
            Mesh->AddSourceModel();FMeshDescription Description;FStaticMeshAttributes Attributes(Description);Attributes.Register();
            TArray<FVertexInstanceID> Corners,WholeCorners;
            for (const FVector3f& Position:Vertices)
            {
                const FVertexID Vertex=Description.CreateVertex();Attributes.GetVertexPositions()[Vertex]=Position;
                Corners.Add(Description.CreateVertexInstance(Vertex));
                if (Lod==0)
                {
                    const FVertexID Joined=Whole.CreateVertex();WholeAttributes.GetVertexPositions()[Joined]=Position;
                    WholeCorners.Add(Whole.CreateVertexInstance(Joined));
                }
            }
            Description.CreateTriangle(Description.CreatePolygonGroup(),Corners);
            if (Lod==0) Whole.CreateTriangle(Whole.CreatePolygonGroup(),WholeCorners);
            Mesh->CreateMeshDescription(Lod,MoveTemp(Description));
        }
        Mesh->SetRenderData(MoveTemp(Data));Parts.Add(Mesh);
    }
    const FBoxSphereBounds Expected=Whole.GetBounds();FBoxSphereBounds Observed(ForceInit);
    TestFalse(TEXT("Existing rigid API still refuses three-LOD assets"),AtomicMeshBounds::MeasureLod0PartsBounds(Parts,Observed));
    TestFalse(TEXT("Unspecified two-LOD policy refuses"),AtomicMeshBounds::MeasureAuthoredLod0PartsBounds(Parts,2,Observed));
    TestTrue(TEXT("Explicit authored family observes saved LOD0"),AtomicMeshBounds::MeasureAuthoredLod0PartsBounds(Parts,3,Observed));
    TestEqual(TEXT("Exact engine description center"),Observed.Origin,Expected.Origin);
    TestEqual(TEXT("Exact engine description extent"),Observed.BoxExtent,Expected.BoxExtent);
    TestEqual(TEXT("Exact engine description true sphere"),Observed.SphereRadius,Expected.SphereRadius);
    TestFalse(TEXT("Duplicate authored member refuses"),AtomicMeshBounds::MeasureAuthoredLod0PartsBounds({Parts[0],Parts[0]},3,Observed));
    TestTrue(TEXT("Production family finishing succeeds"),!UGondolaLogicalMeshComponent::FinishLogicalFamily(TEXT("GD_L1_Rope"),Parts).IsEmpty());
    for (UStaticMesh* Mesh:Parts)
    {
        const auto* Saved=Cast<UGondolaLogicalBoundsData>(Mesh->GetAssetUserDataOfClass(UGondolaLogicalBoundsData::StaticClass()));
        if (!TestNotNull(TEXT("Original logical bounds persisted"),Saved)) return false;
        TestEqual(TEXT("Persisted engine center"),Saved->Origin,Expected.Origin);
        TestEqual(TEXT("Persisted engine extent"),Saved->Extent,Expected.BoxExtent);
        TestEqual(TEXT("Persisted engine sphere"),Saved->Radius,Expected.SphereRadius);
    }
    return true;
}
#endif
