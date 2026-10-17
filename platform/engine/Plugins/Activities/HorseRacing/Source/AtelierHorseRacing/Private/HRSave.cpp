#include "HRSave.h"

#include "HRRules.h"
#include "JsonObjectConverter.h"

namespace HRSave
{
	FString ToJson(const FHRWorldState& S)
	{
		FString Json;
		FJsonObjectConverter::UStructToJsonObjectString(S, Json, 0, 0, 0, nullptr, false);
		return Json;
	}

	bool FromJson(const FString& Json, FHRWorldState& Out)
	{
		FHRWorldState Parsed;
		if (!FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Parsed, 0, 0)) return false;
		if (Parsed.RulesVersion != HRRules::RulesVersion) return false;
		Out = MoveTemp(Parsed);
		return true;
	}
}
