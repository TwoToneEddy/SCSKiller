using SCSKiller.Core.RedEngine;

namespace SCSKiller.Tests.RedEngine;

public class RedShaderCacheFormatTests
{
    // Parser-only fixtures: no D3D compiler, Wine, or game assets required.
    static byte[] Material(uint version, bool lists)
    {
        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write(42UL); writer.Write((byte)0); writer.Write(24); writer.Write(24); writer.Write(new byte[24]);
        var at = stream.Position;
        writer.Write(new byte[24]); writer.Write((byte)0x80); writer.Write(0u);
        writer.Write(42UL); writer.Write(new byte[64]); // eight stage keys plus placeholder
        writer.Write(new byte[16]); // two parameter lists and two name lists
        var size = stream.Position - at;
        if (lists) { writer.Write(1u); writer.Write(0u); writer.Write(new byte[12]); }
        writer.Write(1u); writer.Write(1u); writer.Write(0UL); writer.Write(at); writer.Write(size); writer.Write(at);
        writer.Write("RDHS"u8); writer.Write(version);
        return stream.ToArray();
    }

    [Theory]
    [InlineData(3u, false)]
    [InlineData(5u, true)]
    public void ReadsSupportedLayouts(uint version, bool lists)
    {
        using var stream = new MemoryStream(Material(version, lists));
        var material = Assert.IsType<RedShaderCache.Materials>(RedShaderCache.ReadMaterials(stream));
        Assert.Single(material.Shaders);
        Assert.Equal(42UL, Assert.Single(material.Techniques)[0]);
    }

    [Theory]
    [InlineData(3u, true)]
    [InlineData(5u, false)]
    [InlineData(4u, false)]
    public void RejectsWrongFooterLayout(uint version, bool lists)
    {
        using var stream = new MemoryStream(Material(version, lists));
        Assert.Null(RedShaderCache.ReadMaterials(stream));
    }

    [Theory]
    [InlineData(3u)]
    [InlineData(5u)]
    public void ReadsStaticLayout(uint version)
    {
        using var stream = new MemoryStream();
        using var writer = new BinaryWriter(stream);
        writer.Write(new byte[16]); writer.Write(40); writer.Write(new byte[40]);
        writer.Write(1u); writer.Write(new byte[16]); writer.Write("RDHS"u8); writer.Write(version);
        Assert.Single(RedShaderCache.ReadStatic(stream)!);
    }

    [Fact]
    public void RejectsTruncation()
    {
        var bytes = Material(3, false);
        for (var size = 0; size < bytes.Length; size++)
            Assert.Null(RedShaderCache.ReadMaterials(new MemoryStream(bytes[..size])));
    }
}
