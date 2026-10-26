package com.tus.product.controller;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import com.tus.product.dto.Coupon;
import com.tus.product.model.Product;
import com.tus.product.repos.ProductRepo;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/productapi")
public class ProductRestController {

    @Autowired
    private ProductRepo repo;

    @Autowired
    private RestTemplate restTemplate;

    @Value("${couponService.url}")
    private String couponServiceURL;

    @RequestMapping(value = "/products", method = RequestMethod.POST)
    public Product create(@RequestBody Product product) {
        Coupon coupon = restTemplate.getForObject(couponServiceURL + product.getCouponCode(), Coupon.class);
        product.setPrice(product.getPrice().subtract(coupon.getDiscount()));
        product.setCouponCode(product.getCouponCode());
        return repo.save(product);
    }

    @GetMapping(value = "/products")
    public List<Product> getAllProducts() {
        return repo.findAll();
    }

    @Transactional
    @DeleteMapping(value = "/products")
    public long deleteAllProducts() {
        long count = repo.count();
        repo.deleteAll();
        return count;
    }

    @PostMapping("/products/seed")
    @Transactional
    public long seedProducts(@RequestParam(defaultValue = "100") int count) {

        if (count < 1 || count > 1000) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Count must be between 1 and 1000"
            );
        }

        List<Product> products = new ArrayList<>();

        for (int i = 0; i < count; i++) {
            Product product = new Product();

            product.setName("Test Product " + i);
            product.setDescription("Load testing product " + i);
            product.setPrice(new BigDecimal("100.00"));

            products.add(product);
        }

        repo.saveAll(products);

        return products.size();
    }
}
