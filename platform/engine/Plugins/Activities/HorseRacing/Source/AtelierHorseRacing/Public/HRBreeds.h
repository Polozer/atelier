#pragma once

#include "HRHorseTypes.h"

/** Mesh-independent breed inheritance. Visual genes never alter competitive abilities. */
namespace HRBreeds
{
    inline constexpr const TCHAR* Gene = TEXT("breed");
    inline constexpr int32 AlleleCount = 4;

    /** Alleles: Standard, Giant, Bone, Spirit. Invalid alleles fail explicitly. */
    ATELIERHORSERACING_API const TCHAR* AlleleName(int32 Allele);
    /** Giant is dominant; Bone/Spirit need two copies. An absent gene expresses Standard.
     * Invalid alleles return false without changing Out. */
    ATELIERHORSERACING_API bool TryExpress(const FHRGenePair* Pair, FString& Out);
    /** One inherited allele per parent; an absent parent gene uses the founder distribution.
     * Invalid parent alleles return false without changing Out. Does not mutate either genome. */
    ATELIERHORSERACING_API bool TryGenerate(const FString& Seed, const TMap<FString, FHRGenePair>* Mother,
        const TMap<FString, FHRGenePair>* Father, FHRGenePair& Out);
}
