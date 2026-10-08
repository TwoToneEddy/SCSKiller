using SCSKiller.Core;
using SCSKiller.Core.Planning;
using SCSKiller.Core.RedEngine;

namespace SCSKiller.Tests.RedEngine;

/// <summary>The version 3 cache build's root signatures, against ones vkd3d-proton dumped from the game (Steam build 14504303):
/// descriptions only, no D3D12 runtime needed.</summary>
public class Red3BucketsTests
{
    static ShaderInfo S(Stage stage, params Binding[] b) => new("", stage, "", 0, new(0, 0, 0, 0), b, [], []);
    static Binding B(string cls, int lower, int count = 1, int space = 0) => new(cls, space, lower, count);
    const uint V = 0x10002;   // data volatile, bounds checks kept
    static uint[] Cbv(uint vis, uint n) => [0, vis, 2, n, 0, 0, V];
    static uint[] Srv(uint vis, uint n) => [0, vis, 0, n, 0, 0, V, 0];
    static uint[] Smp(uint vis, uint n) => [0, vis, 3, n, 0, 0, 0];
    static uint[] Uav(uint n) => [0, 0, 1, n, 0, 0, V];
    static RootSig.Desc Build(params ShaderInfo[] s) => RootSig.Build(RootSig.Rule.Red3Buckets, s.ToDictionary(x => x.Stage), false);

    [Fact]
    public void CacheV3ForkPicksTheRule()
    {
        Assert.Equal(RootSig.Rule.Red3Buckets, RootSig.RuleFor(new(RedEngineReader.Family, RedEngineReader.Version, RedEngineReader.CacheV3Fork, "D3D12", false, null)));
        Assert.Equal(RootSig.Rule.Red3, RootSig.RuleFor(new(RedEngineReader.Family, RedEngineReader.Version, null, "D3D12", false, null)));
    }

    [Fact]
    public void GraphicsTablesStepPerStage()
    {
        // dumped 7c5adb6a41a1eb04: PS 8/4/4, VS 4/4/4, absent stages 14/128/16, UAV 4
        var d = Build(S(Stage.Vertex, B("cbv", 0), B("srv", 1)), S(Stage.Pixel, B("cbv", 5), B("srv", 0, 2), B("sampler", 3)));
        Assert.Equal(new RootSig.Desc(0x41, [Cbv(5, 8), Srv(5, 4), Smp(5, 4), Cbv(1, 4), Srv(1, 4), Smp(1, 4),
            Cbv(4, 14), Srv(4, 128), Smp(4, 16), Cbv(2, 14), Srv(2, 128), Smp(2, 16), Cbv(3, 14), Srv(3, 128), Smp(3, 16), Uav(4)]).Key, d.Key);
    }

    [Fact]
    public void ComputeTablesStep()
    {
        // dumped db853535de8ad5d4: 14/32/16/4
        var d = Build(S(Stage.Compute, B("cbv", 12, 2), B("srv", 0, 20), B("sampler", 15), B("uav", 0, 3)));
        Assert.Equal(new RootSig.Desc(0, [Cbv(0, 14), Srv(0, 32), Smp(0, 16), Uav(4)]).Key, d.Key);
    }

    [Fact]
    public void OtherSpacesAndOverflowHaveNone()
    {
        Assert.Throws<RootSig.SerializeException>(() => Build(S(Stage.Compute, B("uav", 0, 1, space: 1))));
        Assert.Throws<RootSig.SerializeException>(() => Build(S(Stage.Compute, B("srv", 0, 129))));
    }
}
