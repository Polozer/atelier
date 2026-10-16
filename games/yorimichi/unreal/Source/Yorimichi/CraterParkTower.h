#pragma once
#include "CoreMinimal.h"

class AWandererCharacter;

/** One way back up Crater Park (docs/CRATERPARK.md, "Tower"): a line's roll-in crest on the tower deck, island cm,
 *  and the Unreal yaw facing down the line. */
struct FCraterParkStart
{
    FString Key, Name;
    FVector Ground = FVector::ZeroVector;
    float Yaw = 0.f;
};

/** The tower starts, from craterpark/park.json: one per designed line (`lines`, ground-checked by the build,
 *  world/regions/craterpark/v2/spawns.py), else the park's single `spawn` (the r4 drop-in). The menu's Crater Park
 *  tower buttons, F7 and the map's Crater Park stop all travel through Return. */
namespace CraterParkTower
{
    /** Read once; empty when the island has no Crater Park data. */
    const TArray<FCraterParkStart>& Starts();
    /** Whether the starts are the generated park's lines (not the fallback drop-in). */
    bool HasLines();
    /** The start F7 uses: the last one chosen this session, the first (the hero line) by default. */
    int32 LastStart();
    /** Put Pawn on start Index, on foot and standing still, facing down its line. Refuses (with a message) unless a
     *  trace from 2 m over the start meets the ground within 50 cm of it: never a floating or buried start. */
    bool Return(AWandererCharacter* Pawn, int32 Index);
}
