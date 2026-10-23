using UnrealBuildTool;

public class AtelierBuildWorker : ModuleRules
{
    public AtelierBuildWorker(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] { "AssetRegistry", "InterchangeEngine", "Json", "Projects", "RHI", "UnrealEd" });
    }
}
