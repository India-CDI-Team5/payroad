#!/usr/bin/env bash
# R13(기사당 동시 활성 호가 상한) 판단 근거를 실측하기 위한 벤치마크.
# accept_offer.lua(R10 정리 루프)가 기사의 활성 호가 수 N에 따라 얼마나 걸리는지 측정한다.
#
# Redis Lua 스크립트 안의 redis.call('TIME')은 결정성 보장을 위해 스크립트 실행 내내
# 고정값을 반환하므로(서버 사이드 자체 계측 불가), 클라이언트(bash+perl)에서
# EVAL 호출 전후 벽시계 시간을 재는 방식으로 측정한다. 이 값에는 redis-cli 프로세스
# 기동/TCP 연결 오버헤드가 constant하게 포함되므로, N에 따른 "증가분"이 핵심 지표다.
#
# 사용법: ./run.sh [redis-port]
# 출처: gutae_edition 브랜치(권구태, 2026-10-04). 결과 요약은 docs/api-spec.md v1.3 R13 표.
set -euo pipefail

PORT="${1:-6399}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER="DR1"
KEY="driver:${DRIVER}:deals"

now_ms() {
    perl -MTime::HiRes=time -e 'printf "%.3f", time()*1000'
}

echo "N,rep_ms_list,min_ms,avg_ms,cleaned_count"

for N in 1 10 50 100 500 1000 5000 10000 50000 100000 500000 1000000; do
    if [ "$N" -le 10000 ]; then
        REPS=5
    else
        REPS=2
    fi

    declare -a TIMES=()
    CLEANED=0

    for ((rep=1; rep<=REPS; rep++)); do
        redis-cli -p "$PORT" flushall > /dev/null
        redis-cli -p "$PORT" --eval "$DIR/seed.lua" "$KEY" , "$N" "$DRIVER" > /dev/null

        T0=$(now_ms)
        RESULT=$(redis-cli -p "$PORT" --eval "$DIR/accept_offer.lua" "$KEY" , "$DRIVER" "NONE")
        T1=$(now_ms)

        ELAPSED=$(perl -e "printf('%.3f', $T1 - $T0)")
        TIMES+=("$ELAPSED")
        CLEANED=$(echo "$RESULT" | sed -n '2p')
    done

    JOINED=$(IFS=';'; echo "${TIMES[*]}")
    MIN=$(printf '%s\n' "${TIMES[@]}" | sort -n | head -1)
    AVG=$(perl -e "my @t=(${TIMES[*]/%/,}); my \$s=0; \$s+=\$_ for @t; printf('%.3f', \$s/scalar(@t))")

    echo "${N},${JOINED},${MIN},${AVG},${CLEANED}"
    unset TIMES
done
