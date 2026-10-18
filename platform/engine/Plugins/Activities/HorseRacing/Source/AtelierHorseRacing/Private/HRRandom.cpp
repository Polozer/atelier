#include "HRRandom.h"

namespace HRRandomPrivate
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

bool HRRandom::TryDraw(const FString& Seed, const FString& Tag, int64 N, int32& Out)
{
    if (N < 1 || N > MAX_int32) return false;
    const uint64 Limit = (4294967296ull / uint64(N)) * uint64(N);
    FString Key;
    Key.Reserve(Seed.Len() + Tag.Len() + 16);
    for (uint64 I = 0;; ++I)
    {
        Key.Reset();
        Key += TEXT("[");
        HRRandomPrivate::AppendJsonString(Key, Seed);
        Key += TEXT(",");
        HRRandomPrivate::AppendJsonString(Key, Tag);
        Key += FString::Printf(TEXT(",%llu]"), I);
        const uint32 Value = Hash(Key);
        if (uint64(Value) < Limit)
        {
            Out = int32(uint64(Value) % uint64(N));
            return true;
        }
    }
}

bool HRRandom::TryPickWeighted(const FString& Seed, const FString& Tag, const TArray<int64>& Weights, int32& Out)
{
    int64 Total = 0;
    for (int64 Weight : Weights)
    {
        if (Weight < 0 || Weight > MAX_int32 - Total) return false;
        Total += Weight;
    }
    int32 Drawn;
    if (!TryDraw(Seed, Tag, Total, Drawn)) return false;
    for (int32 I = 0; I < Weights.Num(); ++I)
    {
        if (Drawn < Weights[I]) { Out = I; return true; }
        Drawn -= int32(Weights[I]);
    }
    return false;
}

int32 HRRandom::Draw(const FString& Seed, const FString& Tag, int64 N)
{
    int32 Result;
    if (TryDraw(Seed, Tag, N, Result)) return Result;
    UE_LOG(LogTemp, Fatal, TEXT("HorseRacing Draw requires a bound in 1..MAX_int32; validate with TryDraw"));
    return 0; // Fatal terminates in every build; never a fallback result.
}

int32 HRRandom::PickWeighted(const FString& Seed, const FString& Tag, const TArray<int64>& Weights)
{
    int32 Result;
    if (TryPickWeighted(Seed, Tag, Weights, Result)) return Result;
    UE_LOG(LogTemp, Fatal, TEXT("HorseRacing PickWeighted requires nonnegative weights with a sum in 1..MAX_int32; validate with TryPickWeighted"));
    return 0;
}
