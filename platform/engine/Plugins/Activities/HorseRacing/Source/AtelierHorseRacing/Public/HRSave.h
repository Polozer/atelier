#pragma once

#include "CoreMinimal.h"
#include "HRTypes.h"

/**
 * The whole racing world as JSON: what a host saves to disk and what it sends as a snapshot to clients. The round trip
 * is lossless, so a reloaded world plays on exactly as the original would.
 */
namespace HRSave
{
	/** Compact JSON of the world (one line). */
	ATELIERHORSERACING_API FString ToJson(const FHRWorldState& S);
	/** Parses a world written by ToJson. False (and Out untouched) when the text is not a world of these rules. */
	ATELIERHORSERACING_API bool FromJson(const FString& Json, FHRWorldState& Out);
}
