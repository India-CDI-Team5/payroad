package com.zerowaiting.dynamicpayroad.repository;

import com.zerowaiting.dynamicpayroad.model.Driver;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface DriverRepository extends JpaRepository<Driver, String> {
    List<Driver> findByStatus(Driver.Status status);
}
