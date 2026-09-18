package com.zerowaiting.dynamicpayroad.repository;

import com.zerowaiting.dynamicpayroad.model.User;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface UserRepository extends JpaRepository<User, String> {
    List<User> findByStatus(User.Status status);
}
