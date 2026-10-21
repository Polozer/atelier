#include "HidamariStable.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "AtelierData.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"

namespace HidamariStableTest
{
    UWorld* GameWorld()
    {
        for (const FWorldContext& Context : GEngine->GetWorldContexts())
            if (Context.World() && Context.World()->IsGameWorld()) return Context.World();
        return nullptr;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHidamariStablePartsAttachedTest, "Yorimichi.Hidamari.StablePartsAttached",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// Every part the stable places hangs on its root at the site (world/regions/hidamari_stable/layout.py SITE), never at
// the island's origin: Unreal refuses to attach a static part to a movable root and leaves it where its site-relative
// placement reads as world coordinates (the barn, its yard and its doors once stood at (0, 0, 0)).
bool FHidamariStablePartsAttachedTest::RunTest(const FString&)
{
    if (!AHidamariStable::bEnabled) { AddInfo(TEXT("The Hidamari stable is disabled")); return true; }
    const FString Path = AtelierDataPath(TEXT("hidamari_stable/stable.json"));
    if (!FPaths::FileExists(Path)) { AddWarning(TEXT("No staged hidamari_stable/stable.json: the check is skipped")); return true; }
    UWorld* World = HidamariStableTest::GameWorld();
    if (!TestNotNull(TEXT("A game world"), World)) return false;
    const bool bExisting = AHidamariStable::Find(World) != nullptr;
    AHidamariStable* Stable = bExisting ? AHidamariStable::Find(World) : AHidamariStable::Spawn(World, Path);
    if (!TestNotNull(TEXT("The stable spawns from the staged data"), Stable)) return false;
    ON_SCOPE_EXIT { if (!bExisting) Stable->Destroy(); };
    TestTrue(TEXT("Every mesh is imported and placed"), Stable->bGameplayReady);
    const FVector Site = Stable->GetActorLocation();
    TArray<UStaticMeshComponent*> Parts;
    Stable->GetComponents(Parts);
    TestTrue(TEXT("The stable has its parts"), Parts.Num() >= 6);
    for (const UStaticMeshComponent* Part : Parts)
    {
        TestTrue(Part->GetName() + TEXT(" hangs on the stable's root"), Part->GetAttachParent() == Stable->GetRootComponent());
        // The pad and its road reach about 100 m from the site; the island's origin is about 1 km away.
        const FVector Centre = Part->Bounds.Origin;
        TestTrue(FString::Printf(TEXT("%s stands at its site (%.0f m away)"), *Part->GetName(), FVector::Dist2D(Centre, Site) / 100.),
                 FVector::Dist2D(Centre, Site) < 150. * 100.);
        TestTrue(FString::Printf(TEXT("%s stands at the site's height (%.1f m from the pad)"), *Part->GetName(), (Centre.Z - Site.Z) / 100.),
                 FMath::Abs(Centre.Z - Site.Z) < 20. * 100.);
    }
    return true;
}
#endif
