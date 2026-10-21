package com.tus.coupon.repo;

import org.springframework.data.jpa.repository.JpaRepository;

import com.tus.coupon.model.Coupon;

public interface CouponRepo extends JpaRepository<Coupon, Long> {

	Coupon findByCode(String code);

}
