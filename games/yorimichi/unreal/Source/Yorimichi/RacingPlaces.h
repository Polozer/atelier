#pragma once
#include "CoreMinimal.h"

class FJsonObject;

/**
 * Belmonte's racing places (docs/RACING.md): the Salon's betting counter and the other racing objects, derived by
 * world/regions/belmonte/build.py (racing_places) from the committed building placements in assets/belmonte/source.json
 * and written into Belmonte's runtime.json ('racing_places'), in Belmonte-local Unreal cm round the region origin, as the
 * TV spots. There is no hardcoded fallback: without valid data a place is simply absent.
 */
namespace RacingPlaces
{
    /** The 'racing_places' object of a Belmonte runtime.json text; null (and OutError) when absent or invalid. */
    YORIMICHI_API TSharedPtr<FJsonObject> Parse(const FString& RuntimeJson, FString* OutError = nullptr);
    /** The staged Belmonte runtime.json's racing places, read and parsed once (the rest of the file is dropped); null
     *  with a logged warning when absent or invalid. */
    YORIMICHI_API TSharedPtr<FJsonObject> Belmonte();
    /** A finite [x, y, z] field; false when absent or invalid. */
    YORIMICHI_API bool Vector(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, FVector& Out);
    /** A finite number field; false when absent or invalid. */
    YORIMICHI_API bool Number(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double& Out);
}
