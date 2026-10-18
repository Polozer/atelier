using UnrealBuildTool;

public class AtelierHorseRacing : ModuleRules
{
    public AtelierHorseRacing(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject" });
    }
}
