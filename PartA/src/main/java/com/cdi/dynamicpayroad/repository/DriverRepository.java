package com.cdi.dynamicpayroad.repository;

import com.cdi.dynamicpayroad.model.Driver;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface DriverRepository extends JpaRepository<Driver, String> {
    List<Driver> findByStatus(Driver.Status status);
}
