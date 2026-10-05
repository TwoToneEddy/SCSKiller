// GNU/LLVM assembler equivalent of stubs.asm for Linux cross-builds.
.text
.globl stub_D3D12CoreCreateLayeredDevice
stub_D3D12CoreCreateLayeredDevice:
    jmp *real_D3D12CoreCreateLayeredDevice(%rip)
.globl stub_D3D12CoreGetLayeredDeviceSize
stub_D3D12CoreGetLayeredDeviceSize:
    jmp *real_D3D12CoreGetLayeredDeviceSize(%rip)
.globl stub_D3D12CoreRegisterLayers
stub_D3D12CoreRegisterLayers:
    jmp *real_D3D12CoreRegisterLayers(%rip)
.globl stub_D3D12CreateRootSignatureDeserializer
stub_D3D12CreateRootSignatureDeserializer:
    jmp *real_D3D12CreateRootSignatureDeserializer(%rip)
.globl stub_D3D12CreateVersionedRootSignatureDeserializer
stub_D3D12CreateVersionedRootSignatureDeserializer:
    jmp *real_D3D12CreateVersionedRootSignatureDeserializer(%rip)
.globl stub_D3D12DeviceRemovedExtendedData
stub_D3D12DeviceRemovedExtendedData:
    jmp *real_D3D12DeviceRemovedExtendedData(%rip)
.globl stub_D3D12EnableExperimentalFeatures
stub_D3D12EnableExperimentalFeatures:
    jmp *real_D3D12EnableExperimentalFeatures(%rip)
.globl stub_D3D12GetDebugInterface
stub_D3D12GetDebugInterface:
    jmp *real_D3D12GetDebugInterface(%rip)
.globl stub_D3D12PIXEventsReplaceBlock
stub_D3D12PIXEventsReplaceBlock:
    jmp *real_D3D12PIXEventsReplaceBlock(%rip)
.globl stub_D3D12PIXGetThreadInfo
stub_D3D12PIXGetThreadInfo:
    jmp *real_D3D12PIXGetThreadInfo(%rip)
.globl stub_D3D12PIXNotifyWakeFromFenceSignal
stub_D3D12PIXNotifyWakeFromFenceSignal:
    jmp *real_D3D12PIXNotifyWakeFromFenceSignal(%rip)
.globl stub_D3D12PIXReportCounter
stub_D3D12PIXReportCounter:
    jmp *real_D3D12PIXReportCounter(%rip)
.globl stub_D3D12SerializeRootSignature
stub_D3D12SerializeRootSignature:
    jmp *real_D3D12SerializeRootSignature(%rip)
.globl stub_D3D12SerializeVersionedRootSignature
stub_D3D12SerializeVersionedRootSignature:
    jmp *real_D3D12SerializeVersionedRootSignature(%rip)
.globl stub_GetBehaviorValue
stub_GetBehaviorValue:
    jmp *real_GetBehaviorValue(%rip)
.globl stub_SetAppCompatStringPointer
stub_SetAppCompatStringPointer:
    jmp *real_SetAppCompatStringPointer(%rip)
.globl stub_Ordinal99
stub_Ordinal99:
    jmp *real_Ordinal99(%rip)
