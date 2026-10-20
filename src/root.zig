const std = @import("std");

pub const bts = @import("binary_tree_set.zig");
pub const bts_std = @import("binary_tree_std.zig");

test "BinaryTreeSet basic tests" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();

    const IntTreeSet = bts.BinaryTreeSet(i32);
    var tree: IntTreeSet.Tree = null;

    const nums = [_]i32{ 5, 3, 8, 1, 4, 6, 9 };
    for (nums) |num| {
        tree = try IntTreeSet.insert(allocator, num, tree);
    }

    try std.testing.expect(IntTreeSet.member2(4, tree, null) == true);
    try std.testing.expect(IntTreeSet.member2(7, tree, null) == false);
    try std.testing.expect(IntTreeSet.member2(5, tree, null) == true);
    try std.testing.expect(IntTreeSet.member2(9, tree, null) == true);
    try std.testing.expect(IntTreeSet.member2(0, tree, null) == false);
}

test "BinaryTreeStd basic tests" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();

    const IntTreeStd = bts_std.BinaryTreeStd(i32);
    var tree: IntTreeStd.Tree = null;

    const nums = [_]i32{ 5, 3, 8, 1, 4, 6, 9 };
    for (nums) |num| {
        tree = try IntTreeStd.insert(allocator, num, tree);
    }

    try std.testing.expect(IntTreeStd.member2(4, tree) == true);
    try std.testing.expect(IntTreeStd.member2(7, tree) == false);
    try std.testing.expect(IntTreeStd.member2(5, tree) == true);
    try std.testing.expect(IntTreeStd.member2(9, tree) == true);
    try std.testing.expect(IntTreeStd.member2(0, tree) == false);
}
