#include "HRRandom.h"

namespace
{
	/** JSON.stringify of a string (the characters our seeds and tags can contain). */
	void AppendJsonString(FString& Out, const FString& S)
	{
		Out += TEXT("\"");
		for (const TCHAR C : S)
		{
			switch (C)
			{
			case TEXT('"'): Out += TEXT("\\\""); break;
			case TEXT('\\'): Out += TEXT("\\\\"); break;
			case TEXT('\n'): Out += TEXT("\\n"); break;
			case TEXT('\r'): Out += TEXT("\\r"); break;
			case TEXT('\t'): Out += TEXT("\\t"); break;
			case TEXT('\b'): Out += TEXT("\\b"); break;
			case TEXT('\f'): Out += TEXT("\\f"); break;
			default:
				if ((uint32)C < 0x20)
				{
					Out += FString::Printf(TEXT("\\u%04x"), (uint32)C);
				}
				else
				{
					Out.AppendChar(C);
				}
			}
		}
		Out += TEXT("\"");
	}
}

uint32 HRRandom::Hash(const FString& Value)
{
	const auto Utf16 = StringCast<UTF16CHAR>(*Value, Value.Len());
	uint32 H = 2166136261u;
	for (int32 I = 0; I < Utf16.Length(); ++I)
	{
		H = (H ^ (uint32)Utf16.Get()[I]) * 16777619u;
	}
	H ^= H >> 16;
	H *= 0x7feb352du;
	H ^= H >> 15;
	H *= 0x846ca68bu;
	return H ^ (H >> 16);
}

int32 HRRandom::Draw(const FString& Seed, const FString& Tag, int64 N)
{
	check(N >= 1);
	const uint64 Limit = (4294967296ull / (uint64)N) * (uint64)N;
	FString Key;
	Key.Reserve(Seed.Len() + Tag.Len() + 16);
	for (int32 I = 0;; ++I)
	{
		Key.Reset();
		Key += TEXT("[");
		AppendJsonString(Key, Seed);
		Key += TEXT(",");
		AppendJsonString(Key, Tag);
		Key += FString::Printf(TEXT(",%d]"), I);
		const uint32 V = Hash(Key);
		if ((uint64)V < Limit)
		{
			return (int32)((uint64)V % (uint64)N);
		}
	}
}

int32 HRRandom::PickWeighted(const FString& Seed, const FString& Tag, const TArray<int64>& Weights)
{
	int64 Total = 0;
	for (const int64 W : Weights)
	{
		Total += W;
	}
	check(Total > 0);
	int64 D = Draw(Seed, Tag, Total);
	for (int32 I = 0; I < Weights.Num(); ++I)
	{
		if (D < Weights[I])
		{
			return I;
		}
		D -= Weights[I];
	}
	return Weights.Num() - 1;
}
