package com.cdi.dynamicpayroad.repository;

import com.cdi.dynamicpayroad.model.DealHistory;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface DealHistoryRepository extends JpaRepository<DealHistory, Long> {

    List<DealHistory> findAllByOrderByIdAsc();

    List<DealHistory> findByExperimentTagOrderByIdAsc(String experimentTag);
}
