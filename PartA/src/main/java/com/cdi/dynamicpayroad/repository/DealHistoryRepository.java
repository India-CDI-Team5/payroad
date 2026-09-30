package com.cdi.dynamicpayroad.repository;

import com.cdi.dynamicpayroad.model.DealHistory;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DealHistoryRepository extends JpaRepository<DealHistory, Long> {
}
