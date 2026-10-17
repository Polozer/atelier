#pragma once

#include "CoreMinimal.h"
#include "HRTypes.h"

struct FHRPhenotype;

/**
 * Horse breeds. A breed is meant to be a mesh (never deformed), the coat a texture painted from the genome's colours,
 * and individuals vary by a uniform scale of +-20 %. Breed x coat x scale gives the variety; visual genes never affect
 * competition. Which mesh a breed uses is the game's business.
 *
 * The breed is one extra gene, "breed" (not part of the 61 reference loci): alleles 0 Standard, 1 Giant, 2 Bone,
 * 3 Spirit. Giant is dominant over Standard; Bone and Spirit are recessive (two copies needed), so the two rare breeds
 * are rare among founders but can be bred from carriers.
 */
namespace HRBreeds
{
	inline constexpr const TCHAR* Gene = TEXT("breed");
	inline constexpr int32 AlleleCount = 4;

	/** Breed id of an allele ("Standard", "Giant", "Bone", "Spirit"). */
	ATELIERHORSERACING_API const TCHAR* AlleleName(int32 Allele);
	/** Expressed breed of a gene pair (Giant dominant, Bone and Spirit recessive); Standard when absent. */
	ATELIERHORSERACING_API FString Express(const FHRGenePair* Pair);
	ATELIERHORSERACING_API FString Express(const TMap<FString, FHRGenePair>& Genome);

	/** Founder draw from the seed, or one allele from each parent. A missing parent side draws like a founder. */
	ATELIERHORSERACING_API FHRGenePair Generate(const FString& Seed, const TMap<FString, FHRGenePair>* Mother, const TMap<FString, FHRGenePair>* Father);

	/** Save migration: gives the breed gene to every horse without it (parents first). Returns the horses completed. */
	ATELIERHORSERACING_API int32 FillMissing(FHRWorldState& S);

	/** Uniform scale of an individual against its breed's neutral adult: 1 +- 0.2 from body.height, foals smaller. */
	ATELIERHORSERACING_API float IndividualScale(const FHRPhenotype& P);
}
