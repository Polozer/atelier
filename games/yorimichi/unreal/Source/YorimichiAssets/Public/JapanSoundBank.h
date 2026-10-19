#pragma once
#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "JapanSoundBank.generated.h"

class USoundWave;

USTRUCT(BlueprintType)
struct YORIMICHIASSETS_API FJapanSoundPool
{
    GENERATED_BODY()
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Audio") TArray<TObjectPtr<USoundWave>> Variants;
};

/** A complete alternative's imported presentation assets. Original uses existing assets directly.
 * SourceManifestHash binds the committed source bank, not a runtime preference or network identity. */
UCLASS(BlueprintType)
class YORIMICHIASSETS_API UJapanSoundBank : public UDataAsset
{
    GENERATED_BODY()
public:
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Audio") FName Key;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Audio") FString SourceManifestHash;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Audio") TMap<FName, FJapanSoundPool> Footsteps;
    /** Runtime must cast/validate USkateSoundSet. Keep this saved-type module independent of
     * Skate gameplay linkage so unrelated character imports do not load its simulation module. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Audio", meta=(AllowedClasses="/Script/AtelierSkate.SkateSoundSet"))
    TObjectPtr<UDataAsset> Skate;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Audio") TObjectPtr<USoundWave> Audition;
};
