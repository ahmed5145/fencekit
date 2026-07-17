"""Lua scripts for atomic lock and fence operations.

Scripts are evaluated with EVAL so they work without prior SCRIPT LOAD.
"""

from __future__ import annotations

# KEYS[1]=lock_key, KEYS[2]=seq_key; ARGV[1]=owner_id, ARGV[2]=ttl_ms.
# Returns a fencing token (integer) or false. INCR happens before SET because
# Redis scripts are atomic but do not roll back writes after a runtime error:
# a corrupt/overflowing counter must not leave a lock without a token.
ACQUIRE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
  return false
end
local token = redis.call('INCR', KEYS[2])
if redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2], 'NX') then
  return token
end
return false
"""

# KEYS[1]=lock_key; ARGV[1]=owner_id
# Returns 1 if deleted, 0 otherwise.
RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

# KEYS[1]=lock_key; ARGV[1]=owner_id, ARGV[2]=ttl_ms
# Returns 1 if extended, 0 otherwise.
EXTEND_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

# KEYS[1]=max_key; ARGV[1]=token
# Returns 1 if accepted (token >= max), 0 if fenced out (token < max).
# Equal tokens are allowed so one acquire can write multiple times.
FENCE_ADVANCE_SCRIPT = """
local max = tonumber(redis.call('GET', KEYS[1]) or '0')
local token = tonumber(ARGV[1])
if token < max then
  return 0
end
redis.call('SET', KEYS[1], ARGV[1])
return 1
"""

# KEYS[1]=max_key; ARGV[1]=token
# Returns 1 if token >= max (allowed), 0 if fenced out. Does not advance.
FENCE_CHECK_SCRIPT = """
local max = tonumber(redis.call('GET', KEYS[1]) or '0')
local token = tonumber(ARGV[1])
if token < max then
  return 0
end
return 1
"""

# KEYS[1]=max_key, KEYS[2]=target_key; ARGV[1]=token, ARGV[2]=value.
# The fence comparison and target mutation are one atomic Redis operation.
FENCED_SET_SCRIPT = """
local max = tonumber(redis.call('GET', KEYS[1]) or '0')
local token = tonumber(ARGV[1])
if token < max then
  return 0
end
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2])
return 1
"""

# KEYS[1]=idem_key, KEYS[2]=result_key;
# ARGV[1]=owner_id, ARGV[2]=ttl_seconds, ARGV[3]=store_result (0|1),
# ARGV[4]=result_json when store_result=1.
# Mark done only for the worker that began. Optionally store a memoized
# result under KEYS[2] with the same TTL. When store_result=0, delete any
# previous result key. Returns 1 if completed.
MARK_DONE_SCRIPT = """
local expected = 'pending:' .. ARGV[1]
if redis.call('GET', KEYS[1]) ~= expected then
  return 0
end
local ttl = tonumber(ARGV[2])
local store_result = tonumber(ARGV[3])
local pttl = -1
if ttl ~= nil and ttl > 0 then
  redis.call('SET', KEYS[1], 'done', 'EX', ttl)
  pttl = ttl * 1000
else
  pttl = redis.call('PTTL', KEYS[1])
  redis.call('SET', KEYS[1], 'done')
  if pttl > 0 then
    redis.call('PEXPIRE', KEYS[1], pttl)
  end
end
if store_result == 1 then
  if pttl > 0 then
    redis.call('SET', KEYS[2], ARGV[4], 'PX', pttl)
  else
    redis.call('SET', KEYS[2], ARGV[4])
  end
else
  redis.call('DEL', KEYS[2])
end
return 1
"""
