#pragma once
#include "CoreMinimal.h"

/** Stateless draws keyed by seed and semantic tag. No mutable random stream is shared between rule operations. */
namespace HRRandom
{
    ATELIERHORSERACING_API uint32 Hash(const FString& Value);
    /** Uniform integer in [0, N), for 1 <= N <= MAX_int32. Invalid input leaves Out unchanged. */
    ATELIERHORSERACING_API bool TryDraw(const FString& Seed, const FString& Tag, int64 N, int32& Out);
    /** Weights must be nonnegative and sum to 1..MAX_int32. Invalid input leaves Out unchanged. */
    ATELIERHORSERACING_API bool TryPickWeighted(const FString& Seed, const FString& Tag, const TArray<int64>& Weights, int32& Out);
    /** Internal rule convenience: callers must validate the range first; invalid input fails explicitly in all builds. */
    ATELIERHORSERACING_API int32 Draw(const FString& Seed, const FString& Tag, int64 N);
    ATELIERHORSERACING_API int32 PickWeighted(const FString& Seed, const FString& Tag, const TArray<int64>& Weights);

    template <typename T>
    TArray<T> Shuffled(const TArray<T>& Items, const FString& Seed, const FString& Tag)
    {
        TArray<T> Copy = Items;
        for (int32 I = Copy.Num() - 1; I > 0; --I)
            Copy.Swap(I, Draw(Seed, FString::Printf(TEXT("%s:%d"), *Tag, I), int64(I) + 1));
        return Copy;
    }
}
