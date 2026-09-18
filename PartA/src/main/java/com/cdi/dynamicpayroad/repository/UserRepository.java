package com.cdi.dynamicpayroad.repository;

import com.cdi.dynamicpayroad.model.User;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface UserRepository extends JpaRepository<User, String> {
    List<User> findByStatus(User.Status status);
}
