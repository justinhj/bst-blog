const std = @import("std");
const zm = @import("zmida");
const bts_std = @import("binary_tree_std.zig");
const bts_sentinel = @import("binary_tree_sentinel.zig");

pub const __zm__callmod__ = std.builtin.CallModifier.never_inline;

const IntTreeStd = bts_std.BinaryTreeStd(f32);
const IntTreeSentinel = bts_sentinel.BinaryTreeSentinel(f32);

const NUM_ELEMENTS: usize = 100_000;
const NUM_ITERATIONS: usize = 10_000;

// Global state — swapped between studies
var g_tree_std: IntTreeStd.Tree = null;
var g_tree_sentinel: IntTreeSentinel = undefined;
var g_search_keys: []f32 = undefined;
var g_key_count: usize = 0;

// ---- bench functions (read from globals) ----

export fn bench_member(_: [*c]f32, _: usize) u64 {
    const keys = g_search_keys[0..g_key_count];
    var hash: u64 = 0;
    for (keys) |key| {
        const found = IntTreeStd.member(key, g_tree_std);
        hash = hash *% 33 +% @as(u64, @intFromBool(found));
    }
    return hash;
}

export fn bench_sentinel(_: [*c]f32, _: usize) u64 {
    const keys = g_search_keys[0..g_key_count];
    var hash: u64 = 0;
    for (keys) |key| {
        const found = g_tree_sentinel.member(key);
        hash = hash *% 33 +% @as(u64, @intFromBool(found));
    }
    return hash;
}

export fn bench_member2(_: [*c]f32, _: usize) u64 {
    const keys = g_search_keys[0..g_key_count];
    var hash: u64 = 0;
    for (keys) |key| {
        const found = IntTreeStd.member2(key, g_tree_std);
        hash = hash *% 33 +% @as(u64, @intFromBool(found));
    }
    return hash;
}

export fn bench_member3(_: [*c]f32, _: usize) u64 {
    const keys = g_search_keys[0..g_key_count];
    var hash: u64 = 0;
    for (keys) |key| {
        const found = IntTreeStd.member3(key, g_tree_std);
        hash = hash *% 33 +% @as(u64, @intFromBool(found));
    }
    return hash;
}

// ---- tree building helpers ----

fn insertBalancedStd(
    allocator: std.mem.Allocator,
    keys: []const f32,
    tree: IntTreeStd.Tree,
) !IntTreeStd.Tree {
    if (keys.len == 0) return tree;
    const mid = keys.len / 2;
    var new_tree = try IntTreeStd.insert(allocator, keys[mid], tree);
    new_tree = try insertBalancedStd(allocator, keys[0..mid], new_tree);
    new_tree = try insertBalancedStd(allocator, keys[mid + 1..], new_tree);
    return new_tree;
}

fn insertBalancedSentinel(
    allocator: std.mem.Allocator,
    keys: []const f32,
    tree: *IntTreeSentinel,
) !void {
    if (keys.len == 0) return;
    const mid = keys.len / 2;
    try tree.insert(allocator, keys[mid]);
    try insertBalancedSentinel(allocator, keys[0..mid], tree);
    try insertBalancedSentinel(allocator, keys[mid + 1..], tree);
}

fn buildBothRandom(allocator: std.mem.Allocator, keys: []const f32) !void {
    g_tree_std = null;
    for (keys) |key| g_tree_std = try IntTreeStd.insert(allocator, key, g_tree_std);

    g_tree_sentinel = try IntTreeSentinel.init(allocator);
    for (keys) |key| try g_tree_sentinel.insert(allocator, key);
}

fn buildBothBalanced(allocator: std.mem.Allocator, keys: []const f32) !void {
    // Sort a copy for balanced insertion
    const sorted = try allocator.alloc(f32, keys.len);
    @memcpy(sorted, keys);
    std.mem.sort(f32, sorted, {}, std.sort.asc(f32));

    g_tree_std = null;
    g_tree_std = try insertBalancedStd(allocator, sorted, g_tree_std);

    g_tree_sentinel = try IntTreeSentinel.init(allocator);
    try insertBalancedSentinel(allocator, sorted, &g_tree_sentinel);

    allocator.free(sorted);
}

// ---- run one study ----

fn runStudy(label: []const u8, out_path: []const u8) !void {
    const funcs = .{ bench_member, bench_sentinel, bench_member2, bench_member3 };
    const args: struct { [*c]f32, usize } = .{ @ptrCast(g_search_keys), g_key_count };

    const config: zm.Config = .byadapt(.{});

    var study = try zm.Study.run(label, config, funcs, args);
    defer study.deinit();

    try study.write_text(out_path, .{ .mode = .thru });
}

pub fn main(init: std.process.Init) !void {
    zm.init(&init, .{ .pin_cpu = 1, .perf_cpu = true, .set_prio = -10 });
    const allocator = init.arena.allocator();

    // Source keys — one set of random f32 values for all trees
    var prng = std.Random.DefaultPrng.init(0x1287ab29);
    const random = prng.random();
    const tree_keys = try allocator.alloc(f32, NUM_ELEMENTS);
    for (tree_keys) |*key| key.* = random.float(f32);

    // Miss keys — fresh random stream, negligible collision with tree_keys
    var miss_prng = std.Random.DefaultPrng.init(0xdeadbeef);
    const miss_random = miss_prng.random();
    const miss_keys = try allocator.alloc(f32, NUM_ITERATIONS);
    for (miss_keys) |*key| key.* = miss_random.float(f32);

    // Hit keys — sample from tree_keys (100% present)
    var hit_prng = std.Random.DefaultPrng.init(0xcafe1234);
    const hit_random = hit_prng.random();
    const hit_keys = try allocator.alloc(f32, NUM_ITERATIONS);
    for (hit_keys) |*key| key.* = tree_keys[hit_random.intRangeLessThan(usize, 0, NUM_ELEMENTS)];

    // ---- 1. Random tree + HITS ----
    try buildBothRandom(allocator, tree_keys);
    g_search_keys = hit_keys;
    g_key_count = NUM_ITERATIONS;
    try runStudy("random-hit", "bst-search-random-hit.txt");


    // ---- 2. Random tree + MISSES ----
    try buildBothRandom(allocator, tree_keys);
    g_search_keys = miss_keys;
    g_key_count = NUM_ITERATIONS;
    try runStudy("random-miss", "bst-search-random-miss.txt");


    // ---- 3. Balanced tree + HITS ----
    try buildBothBalanced(allocator, tree_keys);
    g_search_keys = hit_keys;
    g_key_count = NUM_ITERATIONS;
    try runStudy("balanced-hit", "bst-search-balanced-hit.txt");


    // ---- 4. Balanced tree + MISSES ----
    try buildBothBalanced(allocator, tree_keys);
    g_search_keys = miss_keys;
    g_key_count = NUM_ITERATIONS;
    try runStudy("balanced-miss", "bst-search-balanced-miss.txt");



}