#pragma once
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MeshImportAudit.generated.h"

class UStaticMesh;
class USkeletalMesh;

/** Import audit: exports the actual built LOD geometry for source comparison. */
UCLASS()
class YORIMICHIIMPORT_API UMeshImportAudit : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
public:
    UFUNCTION(BlueprintCallable) static bool DumpMeshTriangles(UStaticMesh* Mesh, FVector Origin, const FString& Path);
    /** LOD 0 of a skeletal mesh as built, as text, to compare two imports (Scripts/character_snapshot.py): a line per
     *  render vertex (`v section x y z nx ny nz u v bone:weight...`, weights 0-1 by bone name), per triangle (`f a b c`)
     *  and per morph target delta (`m target vertex dx dy dz`). */
    UFUNCTION(BlueprintCallable) static bool DumpSkeletalMesh(USkeletalMesh* Mesh, const FString& Path);
};
