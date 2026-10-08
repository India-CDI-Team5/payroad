package com.cdi.dynamicpayroad.redis;

import io.lettuce.core.RedisNoScriptException;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.sync.RedisCommands;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Loads the bargaining scripts of api-spec §6.6 (redis/*.lua, each prefixed with lib/common.lua)
 * with SCRIPT LOAD and calls them with EVALSHA. KEYS are always empty; ARGV[1] is always nowMs.
 * No Spring here: the experiment runner uses it too.
 */
public final class LuaScripts {

    /** Fixed list, read by name from the classpath (works inside a jar; no wildcard lookup). */
    public static final List<String> NAMES = List.of(
            "create_deal", "get_deal", "place_bid", "withdraw_bid", "post_offer",
            "accept_bid", "accept_offer", "cancel_deal", "sweep", "presence_upsert");

    private static final String[] NO_KEYS = new String[0];

    private final RedisCommands<String, String> cmd;
    private final Map<String, String> sources = new HashMap<>();
    private final Map<String, String> shas = new ConcurrentHashMap<>();

    public LuaScripts(RedisCommands<String, String> cmd) {
        this.cmd = cmd;
        String common = read("redis/lib/common.lua");
        for (String name : NAMES) {
            sources.put(name, common + "\n" + read("redis/" + name + ".lua"));
            load(name);
        }
    }

    /** Runs one script and returns its JSON reply. Reloads once if Redis lost the script (NOSCRIPT). */
    public String call(String name, String... argv) {
        String sha = shas.get(name);
        if (sha == null) throw new IllegalArgumentException("unknown script: " + name);
        try {
            return cmd.evalsha(sha, ScriptOutputType.VALUE, NO_KEYS, argv);
        } catch (RedisNoScriptException e) {
            return cmd.evalsha(load(name), ScriptOutputType.VALUE, NO_KEYS, argv);
        }
    }

    private String load(String name) {
        String sha = cmd.scriptLoad(sources.get(name));
        shas.put(name, sha);
        return sha;
    }

    private static String read(String path) {
        try (InputStream in = LuaScripts.class.getClassLoader().getResourceAsStream(path)) {
            if (in == null) throw new IllegalStateException("missing script on classpath: " + path);
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
