#include "HRBreeds.h"
#include "HRRandom.h"

namespace HRBreedsPrivate
{
    const TCHAR* const Alleles[] = {TEXT("Standard"), TEXT("Giant"), TEXT("Bone"), TEXT("Spirit")};
    const TArray<int64> FounderWeights = {74, 12, 7, 7};

    bool Valid(const FHRGenePair* Pair)
    {
        return !Pair || (Pair->A >= 0 && Pair->A < HRBreeds::AlleleCount &&
            Pair->B >= 0 && Pair->B < HRBreeds::AlleleCount);
    }
}

const TCHAR* HRBreeds::AlleleName(int32 Allele)
{
    if (Allele < 0 || Allele >= AlleleCount)
        UE_LOG(LogTemp, Fatal, TEXT("HorseRacing breed allele must be in 0..3"));
    return HRBreedsPrivate::Alleles[Allele];
}

bool HRBreeds::TryExpress(const FHRGenePair* Pair, FString& Out)
{
    if (!HRBreedsPrivate::Valid(Pair)) return false;
    const int32 Allele = !Pair ? 0 : Pair->A == Pair->B ? Pair->A :
        (Pair->A == 1 || Pair->B == 1) ? 1 : 0;
    Out = AlleleName(Allele);
    return true;
}

bool HRBreeds::TryGenerate(const FString& Seed, const TMap<FString, FHRGenePair>* Mother,
    const TMap<FString, FHRGenePair>* Father, FHRGenePair& Out)
{
    const FHRGenePair* Parents[] = {Mother ? Mother->Find(Gene) : nullptr, Father ? Father->Find(Gene) : nullptr};
    if (!HRBreedsPrivate::Valid(Parents[0]) || !HRBreedsPrivate::Valid(Parents[1])) return false;
    int32 Alleles[2];
    for (int32 Side = 0; Side < 2; ++Side)
    {
        Alleles[Side] = Parents[Side]
            ? (*Parents[Side])[HRRandom::Draw(Seed, FString::Printf(TEXT("inherit.breed.%d"), Side), 2)]
            : HRRandom::PickWeighted(Seed, FString::Printf(TEXT("breed.%d"), Side), HRBreedsPrivate::FounderWeights);
    }
    Out = FHRGenePair(Alleles[0], Alleles[1]);
    return true;
}
