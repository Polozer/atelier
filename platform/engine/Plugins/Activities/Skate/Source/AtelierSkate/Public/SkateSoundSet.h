#pragma once
#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "SkateSoundSet.generated.h"

class USoundWave;

USTRUCT(BlueprintType)
struct ATELIERSKATE_API FSkateSoundPool
{
    GENERATED_BODY()
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Skate audio") TArray<TObjectPtr<USoundWave>> Variants;
};

/** Loaded presentation overrides. Absent keys inherit Original. Async loading, saving
 * and complete game-bank coverage belong to the host, independently of simulation. */
UCLASS(BlueprintType)
class ATELIERSKATE_API USkateSoundSet : public UDataAsset
{
    GENERATED_BODY()
public:
    /** Existing cue names: land, land_wood, pop, catch, fall, etc. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Skate audio") TMap<FName, FSkateSoundPool> OneShots;
    /** roll, grind, slide, skid, scrape, then roll_wood/metal/asphalt/stone/dirt/grass/sand. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Skate audio") TMap<FName, TObjectPtr<USoundWave>> Loops;
};
