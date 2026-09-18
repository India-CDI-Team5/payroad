package com.cdi.dynamicpayroad.repository;

import com.cdi.dynamicpayroad.model.MatchResult;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MatchResultRepository extends JpaRepository<MatchResult, Long> {
}
