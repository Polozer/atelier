#include "HRBreeds.h"

#include "HRRandom.h"
#include "HRVisualGenome.h"

namespace
{
	const TCHAR* const GAlleles[HRBreeds::AlleleCount] = {TEXT("Standard"), TEXT("Giant"), TEXT("Bone"), TEXT("Spirit")};
	/** Founder allele weights: about 22 % of founders are Giants, about 0.5 % each Bone and Spirit. */
	const TArray<int64> GFounderWeights = {74, 12, 7, 7};
}

namespace HRBreeds
{
	const TCHAR* AlleleName(int32 Allele)
	{
		return GAlleles[FMath::Clamp(Allele, 0, AlleleCount - 1)];
	}

	FString Express(const FHRGenePair* Pair)
	{
		if (!Pair) return GAlleles[0];
		if (Pair->A == Pair->B) return AlleleName(Pair->A);
		// Giant is dominant over Standard; the rare alleles are recessive (a carrier looks like its other allele).
		if (Pair->A == 1 || Pair->B == 1) return GAlleles[1];
		return GAlleles[0];
	}

	FString Express(const TMap<FString, FHRGenePair>& Genome)
	{
		return Express(Genome.Find(Gene));
	}

	FHRGenePair Generate(const FString& Seed, const TMap<FString, FHRGenePair>* Mother, const TMap<FString, FHRGenePair>* Father)
	{
		const TMap<FString, FHRGenePair>* Parents[2] = {Mother, Father};
		int32 Alleles[2];
		for (int32 Side = 0; Side < 2; ++Side)
		{
			const FHRGenePair* P = Parents[Side] ? Parents[Side]->Find(Gene) : nullptr;
			Alleles[Side] = P ? (*P)[HRRandom::Draw(Seed, FString::Printf(TEXT("inherit.breed.%d"), Side), 2)]
			                  : HRRandom::PickWeighted(Seed, FString::Printf(TEXT("breed.%d"), Side), GFounderWeights);
		}
		return FHRGenePair(Alleles[0], Alleles[1]);
	}

	int32 FillMissing(FHRWorldState& S)
	{
		TArray<FString> Ids;
		S.Horses.GetKeys(Ids);
		Ids.Sort([&S](const FString& A, const FString& B)
		{
			const int32 BA = S.Horses[A].BirthT, BB = S.Horses[B].BirthT;
			return BA != BB ? BA < BB : A.Compare(B, ESearchCase::CaseSensitive) < 0;
		});
		TSet<FString> Done;
		int32 Filled = 0;
		TFunction<void(const FString&)> Complete = [&](const FString& Id)
		{
			bool bSeen = false;
			Done.Add(Id, &bSeen);
			if (bSeen || !S.Horses.Contains(Id) || S.Horses[Id].Genome.Contains(Gene)) return;
			const TArray<FString> ParentIds = S.Horses[Id].Parents;
			const FHRHorse* M = nullptr;
			const FHRHorse* F = nullptr;
			if (ParentIds.Num() == 2)
			{
				Complete(ParentIds[0]);
				Complete(ParentIds[1]);
				M = S.Horses.Find(ParentIds[0]);
				F = S.Horses.Find(ParentIds[1]);
			}
			FHRHorse& H = S.Horses[Id];
			H.Genome.Add(Gene, Generate(H.Seed, M ? &M->Genome : nullptr, F ? &F->Genome : nullptr));
			Filled++;
		};
		for (const FString& Id : Ids) Complete(Id);
		return Filled;
	}

	float IndividualScale(const FHRPhenotype& P)
	{
		// body.height spans -1..1 across its locus range: +-20 %. Foals are scaled down as a whole (a newborn stands at
		// 60 % of its adult size): no deformation at any age.
		const double* W = P.MorphWeights.Find(TEXT("body.height"));
		const float Height = W ? FMath::Clamp((float)*W, -1.f, 1.f) : 0.f;
		return (1.f + 0.2f * Height) * (1.f - 0.4f * (float)P.Juvenile);
	}
}
