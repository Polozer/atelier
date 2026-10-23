#include "AtelierBuildWorkerLibrary.h"

#include "AssetCompilingManager.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "DerivedDataCacheInterface.h"
#include "DerivedDataCacheUsageStats.h"
#include "Editor.h"
#include "Editor/Transactor.h"
#include "Engine/Selection.h"
#include "InterchangeManager.h"
#include "Misc/CoreDelegates.h"
#include "Misc/CoreMisc.h"
#include "UObject/ReferenceChainSearch.h"
#include "UObject/UObjectHash.h"
#include "Dom/JsonObject.h"
#include "HAL/IConsoleManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Modules/ModuleManifest.h"
#include "RHIGlobals.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "ShaderCompiler.h"
#include "UObject/ObjectSaveContext.h"
#include "UObject/Package.h"
#include "UObject/UObjectIterator.h"
#include "UObject/UObjectGlobals.h"

namespace
{
    struct FSaved
    {
        FString Package;
        FString Filename;
    };

    TArray<FSaved> GSaved;
    FDelegateHandle GSaveHandle;
    FDelegateHandle GEnsureHandle;
    int32 GEnsures = 0;

    void OnPackageSaved(const FString& PackageFileName, UPackage* Package, FObjectPostSaveContext)
    {
        GSaved.Add({Package ? Package->GetName() : FString(), FPaths::ConvertRelativePathToFull(PackageFileName)});
    }

    FString Write(const TSharedRef<FJsonValue>& Value)
    {
        FString Text;
        const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
        FJsonSerializer::Serialize(Value, FString(), Writer);
        return Text;
    }

    TSharedRef<FJsonValue> Strings(const TArray<FString>& Values)
    {
        TArray<TSharedPtr<FJsonValue>> Items;
        for (const FString& Value : Values)
        {
            Items.Add(MakeShared<FJsonValueString>(Value));
        }
        return MakeShared<FJsonValueArray>(Items);
    }
}

FString UAtelierBuildWorkerLibrary::NativeContext()
{
    const TSharedRef<FJsonObject> Context = MakeShared<FJsonObject>();
    FModuleManifest Engine;
    const FString EngineBinaries = FPaths::Combine(FPaths::EngineDir(), TEXT("Binaries"), FPlatformProcess::GetBinariesSubdirectory());
    Context->SetStringField(TEXT("build_id"), FModuleManifest::TryRead(FModuleManifest::GetFileName(EngineBinaries, false), Engine) ? Engine.BuildId : FString());

    const FString Project = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
    TArray<FModuleStatus> Statuses;
    FModuleManager::Get().QueryModules(Statuses);
    TArray<FString> Modules, Libraries;
    for (const FModuleStatus& Status : Statuses)
    {
        if (!Status.bIsLoaded || Status.FilePath.IsEmpty())
        {
            continue;
        }
        const FString File = FPaths::ConvertRelativePathToFull(Status.FilePath);
        Libraries.Add(File);
        if (File.StartsWith(FPaths::Combine(Project, TEXT("Binaries"))))
        {
            Modules.Add(Status.Name);
        }
    }
    Modules.Sort();
    Libraries.Sort();
    Context->SetField(TEXT("modules"), Strings(Modules));
    Context->SetField(TEXT("libraries"), Strings(Libraries));

    const TSharedRef<FJsonObject> Plugins = MakeShared<FJsonObject>();
    for (const TSharedRef<IPlugin>& Plugin : IPluginManager::Get().GetEnabledPlugins())
    {
        Plugins->SetStringField(Plugin->GetName(), FPaths::ConvertRelativePathToFull(Plugin->GetBaseDir()));
    }
    Context->SetObjectField(TEXT("plugins"), Plugins);
    Context->SetStringField(TEXT("rhi"), GUsingNullRHI ? TEXT("null") : TEXT("other"));
    return Write(MakeShared<FJsonValueObject>(Context));
}

void UAtelierBuildWorkerLibrary::BeginSaveRecording()
{
    GSaved.Reset();
    if (!GSaveHandle.IsValid())
    {
        GSaveHandle = UPackage::PackageSavedWithContextEvent.AddStatic(&OnPackageSaved);
    }
}

FString UAtelierBuildWorkerLibrary::EndSaveRecording()
{
    if (GSaveHandle.IsValid())
    {
        UPackage::PackageSavedWithContextEvent.Remove(GSaveHandle);
        GSaveHandle.Reset();
    }
    TArray<TSharedPtr<FJsonValue>> Items;
    for (const FSaved& Saved : GSaved)
    {
        const TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
        Item->SetStringField(TEXT("package"), Saved.Package);
        Item->SetStringField(TEXT("filename"), Saved.Filename);
        Items.Add(MakeShared<FJsonValueObject>(Item));
    }
    GSaved.Reset();
    return Write(MakeShared<FJsonValueArray>(Items));
}

void UAtelierBuildWorkerLibrary::FinishBackgroundWork()
{
    FAssetCompilingManager::Get().FinishAllCompilation();
    if (GShaderCompilingManager)
    {
        GShaderCompilingManager->FinishAllCompilation();
    }
    FlushAsyncLoading();
}

TArray<FString> UAtelierBuildWorkerLibrary::DirtyPackageNames()
{
    TArray<FString> Names;
    for (TObjectIterator<UPackage> It; It; ++It)
    {
        if (IsValid(*It) && It->IsDirty())
        {
            Names.Add(It->GetName());
        }
    }
    Names.Sort();
    return Names;
}

TArray<FString> UAtelierBuildWorkerLibrary::LoadedPackageNames(const FString& Prefix)
{
    TArray<FString> Names;
    for (TObjectIterator<UPackage> It; It; ++It)
    {
        if (IsValid(*It) && It->GetName().StartsWith(Prefix))
        {
            Names.Add(It->GetName());
        }
    }
    Names.Sort();
    return Names;
}

FString UAtelierBuildWorkerLibrary::PackageImports(const FString& PackageName)
{
    TArray<FName> Dependencies;
    IAssetRegistry::GetChecked().GetDependencies(FName(*PackageName), Dependencies, UE::AssetRegistry::EDependencyCategory::Package);
    TArray<FString> Names;
    for (const FName& Dependency : Dependencies)
    {
        Names.Add(Dependency.ToString());
    }
    Names.Sort();
    TArray<TSharedPtr<FJsonValue>> Items;
    for (const FString& Name : Names)
    {
        Items.Add(MakeShared<FJsonValueArray>(TArray<TSharedPtr<FJsonValue>>{MakeShared<FJsonValueString>(Name), MakeShared<FJsonValueString>(TEXT("package"))}));
    }
    return Write(MakeShared<FJsonValueArray>(Items));
}

FString UAtelierBuildWorkerLibrary::DdcGraph()
{
    FDerivedDataCacheInterface& Cache = GetDerivedDataCacheRef();
    const TSharedRef<FJsonObject> Graph = MakeShared<FJsonObject>();
    Graph->SetStringField(TEXT("graph"), Cache.GetGraphName());
    TArray<TSharedPtr<FJsonValue>> Nodes;
    PRAGMA_DISABLE_DEPRECATION_WARNINGS
    const TSharedRef<FDerivedDataCacheStatsNode> Stats = Cache.GatherUsageStats();
    PRAGMA_ENABLE_DEPRECATION_WARNINGS
    Stats->ForEachDescendant([&Nodes](TSharedRef<const FDerivedDataCacheStatsNode> Node)
        {
            // The hierarchy and async wrappers carry neither a type nor a path; every store does.
            if (Node->GetCacheType().IsEmpty() && Node->GetCacheName().IsEmpty())
            {
                return;
            }
            const TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
            Entry->SetStringField(TEXT("kind"), Node->GetCacheType());
            Entry->SetStringField(TEXT("path"), Node->GetCacheName().IsEmpty() ? FString() : FPaths::ConvertRelativePathToFull(Node->GetCacheName()));
            Entry->SetBoolField(TEXT("local"), Node->IsLocal());
            Entry->SetStringField(TEXT("status"), Node->GetCacheStatusText());
            Nodes.Add(MakeShared<FJsonValueObject>(Entry));
        });
    Graph->SetArrayField(TEXT("nodes"), Nodes);
    return Write(MakeShared<FJsonValueObject>(Graph));
}

FString UAtelierBuildWorkerLibrary::SettingsSnapshot()
{
    const TSharedRef<FJsonObject> Snapshot = MakeShared<FJsonObject>();
    IConsoleManager::Get().ForEachConsoleObjectThatStartsWith(FConsoleObjectVisitor::CreateLambda(
        [&Snapshot](const TCHAR* Name, IConsoleObject* Object)
        {
            if (IConsoleVariable* Variable = Object ? Object->AsVariable() : nullptr)
            {
                const EConsoleVariableFlags SetBy = EConsoleVariableFlags(Variable->GetFlags() & ECVF_SetByMask);
                Snapshot->SetField(Name, MakeShared<FJsonValueArray>(TArray<TSharedPtr<FJsonValue>>{
                    MakeShared<FJsonValueString>(Variable->GetString()), MakeShared<FJsonValueString>(GetConsoleVariableSetByName(SetBy))}));
            }
        }));
    return Write(MakeShared<FJsonValueObject>(Snapshot));
}

void UAtelierBuildWorkerLibrary::CollectGarbageNow()
{
    CollectGarbage(GARBAGE_COLLECTION_KEEPFLAGS, true);
}

FString UAtelierBuildWorkerLibrary::ReferenceChains(const FString& PackageName)
{
    const TSharedRef<FJsonObject> Chains = MakeShared<FJsonObject>();
    if (UPackage* Package = FindPackage(nullptr, *PackageName))
    {
        TArray<UObject*> Objects;
        GetObjectsWithPackage(Package, Objects, EGetObjectsFlags::None);
        Objects.Add(Package);
        for (UObject* Object : Objects)
        {
            FReferenceChainSearch Search(Object, EReferenceChainSearchMode::Shortest);
            Chains->SetStringField(Object->GetPathName(), Search.GetRootPath());
        }
    }
    return Write(MakeShared<FJsonValueObject>(Chains));
}

bool UAtelierBuildWorkerLibrary::ReleaseEditorState(const FString& Which)
{
    if (Which == TEXT("transactions") && GEditor)
    {
        GEditor->ResetTransaction(NSLOCTEXT("AtelierBuildWorker", "ResetTransaction", "Build worker reset"));
        return true;
    }
    if (Which == TEXT("selection") && GEditor)
    {
        GEditor->SelectNone(false, true, false);
        GEditor->GetSelectedObjects()->DeselectAll();
        GEditor->GetSelectedActors()->DeselectAll();
        GEditor->GetSelectedComponents()->DeselectAll();
        return true;
    }
    if (Which == TEXT("interchange"))
    {
        // No public way to drop Interchange's own state: report whether any import is still active.
        return !UInterchangeManager::GetInterchangeManager().IsInterchangeActive();
    }
    return false;
}

void UAtelierBuildWorkerLibrary::BeginEnsureCount()
{
    GEnsures = 0;
    if (!GEnsureHandle.IsValid())
    {
        GEnsureHandle = FCoreDelegates::OnEnsureFailed.AddLambda(
            [](const ANSICHAR*, const ANSICHAR*, int32, const TCHAR*, const TCHAR*) { ++GEnsures; });
    }
}

int32 UAtelierBuildWorkerLibrary::EnsureCount()
{
    return GEnsures;
}

void UAtelierBuildWorkerLibrary::ForgetFiles(const TArray<FString>& Files)
{
    IAssetRegistry::GetChecked().ScanModifiedAssetFiles(Files);
}
