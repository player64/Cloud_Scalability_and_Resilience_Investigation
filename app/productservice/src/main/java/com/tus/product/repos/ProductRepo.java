package com.tus.product.repos;

import org.springframework.data.jpa.repository.JpaRepository;

import com.tus.product.model.Product;

public interface ProductRepo extends JpaRepository<Product, Long> {

}
