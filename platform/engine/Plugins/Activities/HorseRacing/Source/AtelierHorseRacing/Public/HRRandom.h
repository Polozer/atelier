#pragma once

#include "CoreMinimal.h"

/**
 * Stateless seeded randomness, bit-identical to the reference mobile implementation (src/game/random.ts):
 * FNV-1a over the UTF-16 code units of JSON.stringify([seed, tag, i]) followed by an avalanche.
 * Each semantic draw has its own tag, so no stream ever shares mutable state.
 */
namespace HRRandom
{
	constexpr int32 U = 10000;

	ATELIERHORSERACING_API uint32 Hash(const FString& Value);

	/** Uniform integer in [0, N). */
	ATELIERHORSERACING_API int32 Draw(const FString& Seed, const FString& Tag, int64 N);

	/** Index chosen with integer weights (sum must be positive). */
	ATELIERHORSERACING_API int32 PickWeighted(const FString& Seed, const FString& Tag, const TArray<int64>& Weights);

	/** JS Math.round for the values used here (half rounds up). */
	inline int64 Round(double V) { return (int64)FMath::FloorToDouble(V + 0.5); }

	template <typename T>
	TArray<T> Shuffled(const TArray<T>& Items, const FString& Seed, const FString& Tag)
	{
		TArray<T> Copy = Items;
		for (int32 I = Copy.Num() - 1; I > 0; --I)
		{
			const int32 J = Draw(Seed, FString::Printf(TEXT("%s:%d"), *Tag, I), I + 1);
			Copy.Swap(I, J);
		}
		return Copy;
	}
}
