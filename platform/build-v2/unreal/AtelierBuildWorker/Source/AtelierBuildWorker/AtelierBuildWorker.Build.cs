using UnrealBuildTool;

public class AtelierBuildWorker : ModuleRules
{
    public AtelierBuildWorker(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] { "AssetRegistry", "DerivedDataCache", "InterchangeEngine", "Json", "Projects", "RHI", "UnrealEd" });
    }
}
