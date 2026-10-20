const std = @import("std");
const bts_std = @import("binary_tree_std.zig");
const bts_sentinel = @import("binary_tree_sentinel.zig");

fn parseNumericEnvVar(
    environ_map: anytype,
    name: []const u8,
    default_value: usize,
) usize {
    if (environ_map.get(name)) |val| {
        return std.fmt.parseInt(usize, val, 10) catch |err| {
            std.debug.print("Error: Failed to parse {s} environment variable '{s}': {}\n", .{name, val, err});
            std.process.exit(1);
        };
    }
    return default_value;
}

pub fn main(init: std.process.Init) !void {
    const io = init.io;
    const allocator = init.arena.allocator();

    const num_iterations = parseNumericEnvVar(init.environ_map, "NUM_ITERATIONS", 10_000);
    const num_elements = parseNumericEnvVar(init.environ_map, "NUM_ELEMENTS", 100_000);
    const successful_search = parseNumericEnvVar(init.environ_map, "SUCCESSFUL_SEARCH", 50);
    const balanced = parseNumericEnvVar(init.environ_map, "BALANCED", 0);

    if (num_iterations == 0 or num_elements == 0) {
        std.debug.print("Zero iterations or zero elements requested. Skipping benchmark\n", .{});
        std.process.exit(1);
    }

    if (successful_search > 100) {
        std.debug.print("Error: SUCCESSFUL_SEARCH must be between 0 and 100 percent\n", .{});
        std.process.exit(1);
    }

    if (balanced > 1) {
        std.debug.print("Error: BALANCED must be 0 or 1\n", .{});
        std.process.exit(1);
    }

    // Hardcode a random seed for consistent results across benchmarks
    var prng = std.Random.DefaultPrng.init(0x1287ab29);
    const random = prng.random();

    const keys = try allocator.alloc(f32, num_elements);
    for (keys) |*key| {
        key.* = random.float(f32);
    }

    const method_env = init.environ_map.get("METHOD") orelse "all";
    const run_all = std.mem.eql(u8, method_env, "all");
    const run_std = run_all or std.mem.eql(u8, method_env, "standard");
    const run_sentinel = run_all or std.mem.eql(u8, method_env, "sentinel");
    const run_two = run_all or std.mem.eql(u8, method_env, "twoway");
    const run_three = run_all or std.mem.eql(u8, method_env, "threeway");

    if (!run_std and !run_sentinel and !run_two and !run_three) {
        std.debug.print("Error: Unknown METHOD '{s}'. Expected: all, standard, sentinel, twoway, threeway\n", .{method_env});
        std.process.exit(1);
    }

    // Build the tree to benchmark search on
    const IntTreeStd = bts_std.BinaryTreeStd(f32);
    var tree_std: IntTreeStd.Tree = null;

    const IntTreeSentinel = bts_sentinel.BinaryTreeSentinel(f32);
    var tree_sentinel: ?IntTreeSentinel = null;

    if (run_sentinel) {
        tree_sentinel = try IntTreeSentinel.init(allocator);
    }

    if (balanced == 1) {
        std.mem.sort(f32, keys, {}, std.sort.asc(f32));
        if (run_std or run_two or run_three) {
            tree_std = try insertBalancedStd(allocator, keys, tree_std);
        }
        if (run_sentinel) {
            try insertBalancedSentinel(allocator, keys, &tree_sentinel.?);
        }
    } else {
        if (run_std or run_two or run_three) {
            for (keys) |key| {
                tree_std = try IntTreeStd.insert(allocator, key, tree_std);
            }
        }
        if (run_sentinel) {
            for (keys) |key| {
                try tree_sentinel.?.insert(allocator, key);
            }
        }
    }

    // Generate search queries based on successful_search percentage
    const search_keys = try generateSearchKeys(allocator, random, num_iterations, num_elements, keys, successful_search);
    defer allocator.free(search_keys);

    std.debug.print("Benchmark Results:\n", .{});
    std.debug.print("  Tree Size: {d}\n", .{num_elements});
    std.debug.print("  Iterations: {d}\n\n", .{num_iterations});

    // Run the benchmarks
    if (run_std) {
        var std_hash: u32 = 0;
        const std_start = std.Io.Clock.awake.now(io);
        for (search_keys) |key| {
            const found = IntTreeStd.member(key, tree_std);
            const res = if (found) @as(u32, @bitCast(key)) else 0;
            std_hash = std_hash *% 33 +% res;
        }
        const std_elapsed = std_start.untilNow(io, .awake).nanoseconds;
        std.debug.print("  Standard Search:  {d:.2} ns/op | Total: {d:.2} us (Hash: 0x{x})\n", .{
            @as(f64, @floatFromInt(std_elapsed)) / @as(f64, @floatFromInt(num_iterations)),
            @as(f64, @floatFromInt(std_elapsed)) / 1000.0,
            std_hash,
        });
    }

    if (run_sentinel) {
        var sentinel_hash: u32 = 0;
        const sentinel_start = std.Io.Clock.awake.now(io);
        for (search_keys) |key| {
            const found = tree_sentinel.?.member(key);
            const res = if (found) @as(u32, @bitCast(key)) else 0;
            sentinel_hash = sentinel_hash *% 33 +% res;
        }
        const sentinel_elapsed = sentinel_start.untilNow(io, .awake).nanoseconds;
        std.debug.print("  Sentinel Search:  {d:.2} ns/op | Total: {d:.2} us (Hash: 0x{x})\n", .{
            @as(f64, @floatFromInt(sentinel_elapsed)) / @as(f64, @floatFromInt(num_iterations)),
            @as(f64, @floatFromInt(sentinel_elapsed)) / 1000.0,
            sentinel_hash,
        });
    }

    if (run_two) {
        var two_hash: u32 = 0;
        const two_start = std.Io.Clock.awake.now(io);
        for (search_keys) |key| {
            const found = IntTreeStd.member2(key, tree_std);
            const res = if (found) @as(u32, @bitCast(key)) else 0;
            two_hash = two_hash *% 33 +% res;
        }
        const two_elapsed = two_start.untilNow(io, .awake).nanoseconds;
        std.debug.print("  Two-Way Search:   {d:.2} ns/op | Total: {d:.2} us (Hash: 0x{x})\n", .{
            @as(f64, @floatFromInt(two_elapsed)) / @as(f64, @floatFromInt(num_iterations)),
            @as(f64, @floatFromInt(two_elapsed)) / 1000.0,
            two_hash,
        });
    }

    if (run_three) {
        var three_hash: u32 = 0;
        const three_start = std.Io.Clock.awake.now(io);
        for (search_keys) |key| {
            const found = IntTreeStd.member3(key, tree_std);
            const res = if (found) @as(u32, @bitCast(key)) else 0;
            three_hash = three_hash *% 33 +% res;
        }
        const three_elapsed = three_start.untilNow(io, .awake).nanoseconds;
        std.debug.print("  Three-Way Search: {d:.2} ns/op | Total: {d:.2} us (Hash: 0x{x})\n", .{
            @as(f64, @floatFromInt(three_elapsed)) / @as(f64, @floatFromInt(num_iterations)),
            @as(f64, @floatFromInt(three_elapsed)) / 1000.0,
            three_hash,
        });
    }
}

fn insertBalancedStd(
    allocator: std.mem.Allocator,
    keys: []const f32,
    tree: bts_std.BinaryTreeStd(f32).Tree,
) !bts_std.BinaryTreeStd(f32).Tree {
    if (keys.len == 0) return tree;
    const mid = keys.len / 2;
    var new_tree = try bts_std.BinaryTreeStd(f32).insert(allocator, keys[mid], tree);
    new_tree = try insertBalancedStd(allocator, keys[0..mid], new_tree);
    new_tree = try insertBalancedStd(allocator, keys[mid + 1..], new_tree);
    return new_tree;
}

fn insertBalancedSentinel(
    allocator: std.mem.Allocator,
    keys: []const f32,
    tree: *bts_sentinel.BinaryTreeSentinel(f32),
) !void {
    if (keys.len == 0) return;
    const mid = keys.len / 2;
    try tree.insert(allocator, keys[mid]);
    try insertBalancedSentinel(allocator, keys[0..mid], tree);
    try insertBalancedSentinel(allocator, keys[mid + 1..], tree);
}

pub fn generateSearchKeys(
    allocator: std.mem.Allocator,
    random: std.Random,
    num_iterations: usize,
    num_elements: usize,
    keys: []const f32,
    successful_search: usize,
) ![]f32 {
    const search_keys = try allocator.alloc(f32, num_iterations);
    errdefer allocator.free(search_keys);
    for (search_keys) |*key| {
        if (random.intRangeLessThan(usize, 0, 100) < successful_search) {
            key.* = keys[random.intRangeLessThan(usize, 0, num_elements)];
        } else {
            key.* = random.float(f32);
        }
    }
    return search_keys;
}

test "generateSearchKeys ratio verification" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();

    var prng = std.Random.DefaultPrng.init(0);
    const random = prng.random();

    // Create a small keys array
    const keys = try allocator.alloc(f32, 10);
    for (keys) |*k| {
        k.* = random.float(f32);
    }

    // Test 100% hits
    {
        const search_keys = try generateSearchKeys(allocator, random, 1000, keys.len, keys, 100);
        defer allocator.free(search_keys);
        
        var hit_count: usize = 0;
        for (search_keys) |k| {
            if (std.mem.indexOfScalar(f32, keys, k) != null) {
                hit_count += 1;
            }
        }
        try std.testing.expectEqual(@as(usize, 1000), hit_count);
    }

    // Test 0% hits (100% misses)
    {
        const search_keys = try generateSearchKeys(allocator, random, 1000, keys.len, keys, 0);
        defer allocator.free(search_keys);
        
        var hit_count: usize = 0;
        for (search_keys) |k| {
            if (std.mem.indexOfScalar(f32, keys, k) != null) {
                hit_count += 1;
            }
        }
        // Misses should generate random floats, which have virtually 0 probability of colliding with keys
        try std.testing.expectEqual(@as(usize, 0), hit_count);
    }

    // Test 50% hits
    {
        const search_keys = try generateSearchKeys(allocator, random, 1000, keys.len, keys, 50);
        defer allocator.free(search_keys);
        
        var hit_count: usize = 0;
        for (search_keys) |k| {
            if (std.mem.indexOfScalar(f32, keys, k) != null) {
                hit_count += 1;
            }
        }
        // With 1000 iterations, 50% hit probability should yield around 500 hits.
        // We can allow a small tolerance (e.g. between 450 and 550) for statistical variance.
        try std.testing.expect(hit_count >= 450 and hit_count <= 550);
    }
}
