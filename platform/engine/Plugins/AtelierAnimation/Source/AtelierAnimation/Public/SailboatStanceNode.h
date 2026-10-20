#pragma once
#include "BoneControllers/AnimNode_SkeletalControlBase.h"
#include "TwoBoneIK.h"
/** Seated helm pose: hips/feet supported by the boat, articulated overhand tiller grip. With bGripLeft the left hand
 *  wraps its own target too (a steering wheel held at both sides); otherwise it rests as a plain wrist target. */
struct FSailboatStanceNode final : public FAnimNode_SkeletalControlBase
{
 enum{Pelvis,Spine,Chest,Neck,Head,UpperL,ForeL,HandL,UpperR,ForeR,HandR,ThighL,ShinL,FootL,ThighR,ShinR,FootR,Finger0,Tip0,Finger1,Tip1,Finger2,Tip2,Finger3,Tip3,Thumb,
      FingerL0,TipL0,FingerL1,TipL1,FingerL2,TipL2,FingerL3,TipL3,ThumbL,Count};
 FBoneReference Bones[Count];
 FVector PelvisTarget,HandTarget[2],ElbowPole[2],FootTarget[2],KneePole[2];
 FVector GripAxis=FVector::UpVector,GripUp=FVector::UpVector,GripForward=FVector::ForwardVector;
 /** The left hand grips too, with these axes (a wheel's rim rather than the tiller). */
 bool bGripLeft=false;
 FVector GripAxisL=FVector::UpVector,GripUpL=FVector::LeftVector,GripForwardL=FVector::ForwardVector;
 /** Degrees the upper body leans back from the pelvis, over a reclined seat (0 keeps the source pose). */
 float TorsoRecline=0.f;
 FSailboatStanceNode()
 {
  const TCHAR* Names[]={TEXT("pelvis"),TEXT("spine"),TEXT("chest"),TEXT("neck"),TEXT("head"),TEXT("upperarm_L"),TEXT("forearm_L"),TEXT("hand_L"),TEXT("upperarm_R"),TEXT("forearm_R"),TEXT("hand_R"),TEXT("thigh_L"),TEXT("shin_L"),TEXT("foot_L"),TEXT("thigh_R"),TEXT("shin_R"),TEXT("foot_R"),TEXT("finger_0_R"),TEXT("finger_tip_0_R"),TEXT("finger_1_R"),TEXT("finger_tip_1_R"),TEXT("finger_2_R"),TEXT("finger_tip_2_R"),TEXT("finger_3_R"),TEXT("finger_tip_3_R"),TEXT("thumb_R"),
                        TEXT("finger_0_L"),TEXT("finger_tip_0_L"),TEXT("finger_1_L"),TEXT("finger_tip_1_L"),TEXT("finger_2_L"),TEXT("finger_tip_2_L"),TEXT("finger_3_L"),TEXT("finger_tip_3_L"),TEXT("thumb_L")};
  for(int I=0;I<Count;++I)Bones[I].BoneName=Names[I];
 }
 virtual void InitializeBoneReferences(const FBoneContainer& C) override{for(auto& B:Bones)B.Initialize(C);}
 virtual bool IsValidToEvaluate(const USkeleton*,const FBoneContainer& C) override{for(const auto& B:Bones)if(!B.IsValidToEvaluate(C))return false;return true;}
 virtual void EvaluateSkeletalControl_AnyThread(FComponentSpacePoseContext& Output,TArray<FBoneTransform>& Result) override
 {
  const auto& C=Output.Pose.GetPose().GetBoneContainer();FCompactPoseBoneIndex Indices[Count];FTransform P[Count];
  for(int I=0;I<Count;++I){Indices[I]=Bones[I].GetCompactPoseIndex(C);P[I]=Output.Pose.GetComponentSpaceTransform(Indices[I]);}
  const FVector Shift=PelvisTarget-P[Pelvis].GetLocation();for(auto& T:P)T.AddToTranslation(Shift);
  if(TorsoRecline!=0.f)
  {
   const FQuat Recline(FVector::RightVector,FMath::DegreesToRadians(-TorsoRecline));
   const FVector Pivot=P[Pelvis].GetLocation();
   for(int I=0;I<Count;++I)
   {
    if(I==Pelvis||(I>=ThighL&&I<=FootR))continue;
    P[I].SetLocation(Pivot+Recline.RotateVector(P[I].GetLocation()-Pivot));
    P[I].SetRotation(Recline*P[I].GetRotation());
   }
   const FQuat Look(FVector::RightVector,FMath::DegreesToRadians(TorsoRecline*.6f));
   const FVector HeadPivot=P[Neck].GetLocation();
   for(int I: {Neck,Head})
   {
    P[I].SetLocation(HeadPivot+Look.RotateVector(P[I].GetLocation()-HeadPivot));
    P[I].SetRotation(Look*P[I].GetRotation());
   }
  }
  // The rim is about 3.2cm thick: the knuckles sit above its top and the fingertips wrap around its outer face.
  auto grip=[&](int Hand,int Finger,int Upper,int Fore,int Side,const FVector& Target,const FVector& Forward,const FVector& Up,const FVector& Axis)
  {
   const FTransform OldHand=P[Hand];
   // Derive the imported hand's anatomical axes from its knuckles, not assumed FBX bone axes.
   FVector Knuckles=FVector::ZeroVector;for(int I=0;I<4;++I)Knuckles+=P[Finger+2*I].GetLocation();Knuckles*=.25;
   const FVector OldForward=(Knuckles-OldHand.GetLocation()).GetSafeNormal();
   const FVector OldSpan=(P[Finger+6].GetLocation()-P[Finger].GetLocation()).GetSafeNormal();
   const FQuat First=FQuat::FindBetweenNormals(OldForward,Forward);
   const FVector Span=FVector::VectorPlaneProject(First.RotateVector(OldSpan),Forward).GetSafeNormal();
   const FVector WantSpan=FVector::VectorPlaneProject(Axis,Forward).GetSafeNormal();
   const FQuat Align=FQuat::FindBetweenNormals(Span,WantSpan)*First;
   const FQuat HandRotation=Align*OldHand.GetRotation();
   const FVector DesiredKnuckles=Target+Forward*1.2f+Up*2.8f;
   const FVector Wrist=DesiredKnuckles-Align.RotateVector(Knuckles-OldHand.GetLocation());
   AnimationCore::SolveTwoBoneIK(P[Upper],P[Fore],P[Hand],ElbowPole[Side],Wrist,false,1.,1.);
   P[Hand].SetRotation(HandRotation);
   const FTransform NewHand=P[Hand];
   for(int I=0;I<4;++I)
   {
    const int F=Finger+I*2,T=F+1;
    const FTransform OriginalFinger=P[F],OriginalTip=P[T];
    const FVector BoneDirection=(OriginalTip.GetLocation()-OriginalFinger.GetLocation()).GetSafeNormal();
    const FVector BoneLocalAxis=OriginalFinger.GetRotation().UnrotateVector(BoneDirection);
    const float Length=FVector::Distance(OriginalTip.GetLocation(),OriginalFinger.GetLocation());
    P[F]=OriginalFinger.GetRelativeTransform(OldHand)*NewHand;
    const FVector Across=(Forward*.43f-Up*.90f).GetSafeNormal();
    const FVector Under=(-Forward*.70f-Up*.71f).GetSafeNormal();
    const FVector Tip=P[F].GetLocation()+Across*Length;
    P[F].SetRotation(FQuat::FindBetweenNormals(P[F].GetRotation().RotateVector(BoneLocalAxis),Across)*P[F].GetRotation());
    P[T]=OriginalTip.GetRelativeTransform(OldHand)*NewHand;
    P[T].SetLocation(Tip);
    P[T].SetRotation(FQuat::FindBetweenNormals(P[T].GetRotation().RotateVector(BoneLocalAxis),Under)*P[T].GetRotation());
   }
   // Opposing thumb approaches the inner side of the grip, rather than hanging with the fingers.
   const int ThumbBone=Finger+8;
   const FVector ThumbAxis=P[Finger].GetRotation().UnrotateVector((Forward*.43f-Up*.90f).GetSafeNormal());
   P[ThumbBone]=P[ThumbBone].GetRelativeTransform(OldHand)*NewHand;
   const FVector ThumbToward=(Target-Forward*1.8f-Up*.8f-P[ThumbBone].GetLocation()).GetSafeNormal();
   P[ThumbBone].SetRotation(FQuat::FindBetweenNormals(P[ThumbBone].GetRotation().RotateVector(ThumbAxis),ThumbToward)*P[ThumbBone].GetRotation());
  };
  grip(HandR,Finger0,UpperR,ForeR,1,HandTarget[1],GripForward,GripUp,GripAxis);
  if(bGripLeft)grip(HandL,FingerL0,UpperL,ForeL,0,HandTarget[0],GripForwardL,GripUpL,GripAxisL);
  for(int Side=0;Side<2;++Side)
  {
   const int U=Side?ThighR:ThighL;const FQuat FootRotation=P[U+2].GetRotation();
   AnimationCore::SolveTwoBoneIK(P[U],P[U+1],P[U+2],KneePole[Side],FootTarget[Side],false,1.,1.);P[U+2].SetRotation(FootRotation);
  }
  if(!bGripLeft)AnimationCore::SolveTwoBoneIK(P[UpperL],P[ForeL],P[HandL],ElbowPole[0],HandTarget[0],false,1.,1.);
  // The left fingers only move when the left hand grips its own target. Otherwise leave them out, so the
  // pose keeps the free wrist's own child propagation (the sailing tiller hand).
  for(int I=0;I<Count;++I){if(!bGripLeft&&I>=FingerL0)continue;Result.Emplace(Indices[I],P[I]);}
  Result.Sort(FCompareBoneTransformIndex());
 }
};
